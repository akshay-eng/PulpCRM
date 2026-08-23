"""Permission-aware CRM assistant with previewed, auditable actions.

The model is a planner, not a database client. It may select one of the actions
described in ``SYSTEM`` and return JSON. Every doctype, field, filter and target
is validated in Python. Reads continue through ``frappe.get_list`` so normal
row permissions apply. Writes are stored as a pending action and run only after
the same user explicitly confirms them in Ask Pulp.
"""

import json

import frappe
from frappe import _

from baton.audit import log_action
from baton.llm import chat_json, use_client_credential

ALLOWED_DOCTYPES = [
	"CRM Lead",
	"CRM Deal",
	"Contact",
	"CRM Organization",
	"CRM Task",
	"FCRM Note",
	"CRM Call Log",
	"Baton Approval",
	"Baton Workflow Run",
]

WRITABLE_DOCTYPES = [
	"CRM Lead",
	"CRM Deal",
	"Contact",
	"CRM Organization",
	"CRM Task",
	"FCRM Note",
]

PROTECTED_FIELDS = {
	"name",
	"owner",
	"doctype",
	"docstatus",
	"creation",
	"modified",
	"modified_by",
	"parent",
	"parenttype",
	"parentfield",
	"idx",
	"_assign",
	"_comments",
	"_user_tags",
	"_liked_by",
}

NON_WRITABLE_FIELDTYPES = {
	"Section Break",
	"Column Break",
	"Tab Break",
	"HTML",
	"Button",
	"Table",
	"Table MultiSelect",
	"Password",
	"Attach",
	"Attach Image",
	"Signature",
	"Code",
}

ALLOWED_OPERATORS = {
	"=",
	"!=",
	">",
	"<",
	">=",
	"<=",
	"like",
	"not like",
	"in",
	"not in",
	"between",
	"is",
}

WRITE_ACTIONS = {"update", "create", "assign", "add_comment", "convert_lead"}
MAX_LIMIT = 200
MAX_EXPORT_ROWS = 5000
MAX_ACTION_ROWS = 20
MAX_CONTEXT_MESSAGES = 8


def _is_writable_field(field):
	return bool(
		field
		and field.fieldname not in PROTECTED_FIELDS
		and not str(field.fieldname).startswith("_")
		and field.fieldtype not in NON_WRITABLE_FIELDTYPES
		and not field.read_only
		and not field.hidden
		and not field.set_only_once
		and not field.permlevel
	)


def _catalog():
	"""Compact schema given to the planner, including its write boundary."""
	out = []
	for doctype in ALLOWED_DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		meta = frappe.get_meta(doctype)
		fields = []
		for field in meta.fields:
			if field.fieldtype in ("Section Break", "Column Break", "Tab Break", "HTML", "Table"):
				continue
			access = "write" if doctype in WRITABLE_DOCTYPES and _is_writable_field(field) else "read"
			fields.append(f"{field.fieldname}:{field.fieldtype}:{access}")
		out.append(
			f"{doctype} -> name:Data:read, owner:Link:read, "
			f"creation:Datetime:read, modified:Datetime:read, " + ", ".join(fields[:55])
		)
	return "\n".join(out)


SYSTEM = """You are the action planner for Pulp, a CRM assistant. Convert the
user's request into ONE JSON object. You may choose these actions:

query:
{{"action":"query","doctype":"...","fields":["name",...],"filters":{{...}},
  "order_by":"modified desc","limit":20,"summarize":false,"explanation":"..."}}
export:
{{"action":"export","doctype":"...","fields":["name",...],"filters":{{...}},
  "order_by":"modified desc","limit":5000,"file_format":"CSV","explanation":"..."}}
update (requires confirmation):
{{"action":"update","doctype":"...","filters":{{...}},
  "values":{{"field":"new value"}},"explanation":"..."}}
create (requires confirmation):
{{"action":"create","doctype":"...","values":{{...}},"explanation":"..."}}
assign (requires confirmation):
{{"action":"assign","doctype":"...","filters":{{...}},"assignee":"email or exact name",
  "explanation":"..."}}
add_comment (requires confirmation):
{{"action":"add_comment","doctype":"...","filters":{{...}},"comment":"...",
  "explanation":"..."}}
convert_lead (requires confirmation):
{{"action":"convert_lead","doctype":"CRM Lead","filters":{{...}},"explanation":"..."}}
help or small talk:
{{"action":"help","doctype":null,"explanation":"..."}}

Rules:
- Return only the JSON object. Never write SQL and never invent a doctype or field.
- Use only the schema below. Fields marked read cannot be changed.
- Always include name in query/export fields.
- Use filters that identify exactly what the user meant. For a named record,
  filter its visible name/title field with = or like. Never plan an unfiltered write.
- Operators: =, !=, >, <, >=, <=, like, not like, in, not in, between, is.
- For recent/latest, order by modified desc or creation desc.
- For dates use YYYY-MM-DD and ["between", [start, end]]. Today is {today}.
- Use summarize=true when the user asks for a conclusion, comparison, pattern,
  prioritization or summary rather than simply asking to see rows.
- Export CSV unless the user explicitly requests Excel.
- Never delete records, send messages, or invent unsupported actions. Explain the
  limitation with action=help instead.
- Follow-up requests may refer to records in Conversation context. Resolve those
  references from the stored action/query details there.

Schema:
{schema}"""


def _valid_fields(doctype):
	meta = frappe.get_meta(doctype)
	return {field.fieldname for field in meta.fields} | PROTECTED_FIELDS


def _clean_filters(doctype, raw):
	if raw in (None, ""):
		return {}
	if not isinstance(raw, dict):
		frappe.throw(_("The assistant produced invalid filters."))

	valid = _valid_fields(doctype)
	filters = {}
	for fieldname, value in raw.items():
		if fieldname not in valid:
			frappe.throw(_("{0} has no field called {1}.").format(doctype, fieldname))
		if isinstance(value, list):
			if len(value) != 2 or str(value[0]).lower() not in ALLOWED_OPERATORS:
				frappe.throw(_("The assistant produced an invalid filter operator."))
			value = [str(value[0]).lower(), value[1]]
		elif isinstance(value, dict):
			frappe.throw(_("The assistant produced an invalid filter value."))
		filters[fieldname] = value
	return filters


def _validate_query(spec, max_limit=MAX_LIMIT):
	doctype = spec.get("doctype")
	if not doctype:
		return None, [], {}, None, 0
	if doctype not in ALLOWED_DOCTYPES:
		frappe.throw(_("The assistant may not read {0}.").format(doctype))

	valid = _valid_fields(doctype)
	fields = [field for field in (spec.get("fields") or ["name"]) if field in valid]
	if not fields:
		fields = ["name"]
	if "name" not in fields:
		fields.insert(0, "name")
	fields = list(dict.fromkeys(fields))[:30]

	filters = _clean_filters(doctype, spec.get("filters"))
	order_by = str(spec.get("order_by") or "modified desc").strip()
	parts = order_by.split()
	if len(parts) not in (1, 2) or parts[0] not in valid:
		order_by = "modified desc"
	else:
		direction = parts[1].lower() if len(parts) == 2 else "asc"
		order_by = f"{parts[0]} {direction}" if direction in ("asc", "desc") else "modified desc"

	try:
		limit = max(1, min(int(spec.get("limit") or 20), max_limit))
	except (TypeError, ValueError):
		limit = 20
	return doctype, fields, filters, order_by, limit


def _validate(spec):
	"""Backwards-compatible public validator used by integrations and tests."""
	return _validate_query(spec)


def _clean_values(doctype, raw):
	if doctype not in WRITABLE_DOCTYPES:
		frappe.throw(_("Ask Pulp may not change {0}.").format(doctype))
	if not isinstance(raw, dict) or not raw:
		frappe.throw(_("No values were provided for this change."))

	meta = frappe.get_meta(doctype)
	values = {}
	for fieldname, value in raw.items():
		field = meta.get_field(fieldname)
		if not _is_writable_field(field):
			frappe.throw(_("Ask Pulp may not change {0}.{1}.").format(doctype, fieldname))
		if isinstance(value, (dict, list)):
			frappe.throw(_("The value for {0} must be a single value.").format(fieldname))
		values[fieldname] = value
	return values


def _owned_session(session):
	doc = frappe.get_doc("Baton Chat Session", session)
	if doc.user != frappe.session.user:
		frappe.throw(_("This chat belongs to another user."), frappe.PermissionError)
	return doc


def _conversation_context(session):
	if not session:
		return []
	_owned_session(session)
	messages = frappe.get_all(
		"Baton Chat Message",
		filters={"session": session},
		fields=["role", "content", "query_spec"],
		order_by="creation desc",
		limit_page_length=MAX_CONTEXT_MESSAGES,
	)
	context = []
	for message in reversed(messages):
		content = message.content or ""
		if message.query_spec:
			content += f"\nStored action/query details: {message.query_spec[:3000]}"
		context.append({"role": message.role, "content": content[:5000]})
	return context


def _new_session(question):
	return frappe.get_doc(
		{
			"doctype": "Baton Chat Session",
			"title": question[:110],
			"user": frappe.session.user,
		}
	).insert(ignore_permissions=True)


def _store_message(session, role, content, query_spec=None, row_count=0):
	return frappe.get_doc(
		{
			"doctype": "Baton Chat Message",
			"session": session,
			"role": role,
			"content": content,
			"query_spec": json.dumps(query_spec, indent=1, default=str) if query_spec else None,
			"row_count": row_count,
		}
	).insert(ignore_permissions=True)


def _preview_fields(doctype, extra=None):
	meta = frappe.get_meta(doctype)
	candidates = ["name", meta.title_field]
	candidates.extend(extra or [])
	return list(dict.fromkeys(field for field in candidates if field and field in _valid_fields(doctype)))


def _target_rows(doctype, filters, extra_fields=None):
	if not filters:
		frappe.throw(_("Please identify which record should be changed."))
	rows = frappe.get_list(
		doctype,
		fields=_preview_fields(doctype, extra_fields),
		filters=filters,
		order_by="modified desc",
		limit_page_length=MAX_ACTION_ROWS + 1,
	)
	if not rows:
		frappe.throw(_("No matching {0} records were found.").format(doctype))
	if len(rows) > MAX_ACTION_ROWS:
		frappe.throw(
			_("That would change more than {0} records. Narrow the request first.").format(MAX_ACTION_ROWS)
		)
	return rows


def _resolve_user(value):
	value = str(value or "").strip()
	if not value:
		frappe.throw(_("Choose a user to assign the record to."))
	for filters in ({"name": value, "enabled": 1}, {"full_name": value, "enabled": 1}):
		user = frappe.db.get_value("User", filters, "name")
		if user:
			return user
	frappe.throw(_("No enabled user matches {0}.").format(value))


def _pending_action(spec):
	action = spec.get("action")
	doctype = spec.get("doctype")
	if action != "convert_lead" and doctype not in WRITABLE_DOCTYPES:
		frappe.throw(_("Ask Pulp may not change {0}.").format(doctype or "that record type"))
	if action == "convert_lead" and doctype != "CRM Lead":
		frappe.throw(_("Only leads can be converted to deals."))

	filters = _clean_filters(doctype, spec.get("filters")) if action != "create" else {}
	plan = {
		"kind": "pending_action",
		"status": "pending",
		"action": action,
		"doctype": doctype,
		"explanation": str(spec.get("explanation") or "").strip(),
	}

	if action == "create":
		plan["values"] = _clean_values(doctype, spec.get("values"))
		rows = []
	else:
		extra_fields = list((spec.get("values") or {}).keys()) if action == "update" else []
		rows = _target_rows(doctype, filters, extra_fields)
		plan["names"] = [row.name for row in rows]

	if action == "update":
		plan["values"] = _clean_values(doctype, spec.get("values"))
	elif action == "assign":
		plan["assignee"] = _resolve_user(spec.get("assignee"))
	elif action == "add_comment":
		comment = str(spec.get("comment") or "").strip()
		if not comment:
			frappe.throw(_("A comment needs some text."))
		plan["comment"] = comment[:4000]

	return plan, rows


def _action_summary(plan):
	action = plan["action"]
	doctype = plan["doctype"]
	count = len(plan.get("names") or [])
	if action == "update":
		changes = ", ".join(f"{field} → {value}" for field, value in plan["values"].items())
		return _("Ready to update {0} {1}: {2}").format(count, doctype, changes)
	if action == "create":
		return _("Ready to create one {0}.").format(doctype)
	if action == "assign":
		return _("Ready to assign {0} {1} to {2}.").format(count, doctype, plan["assignee"])
	if action == "add_comment":
		return _("Ready to add a comment to {0} {1}.").format(count, doctype)
	if action == "convert_lead":
		return _("Ready to convert {0} lead(s) to deals.").format(count)
	return _("This action is ready for confirmation.")


def _summarize(question, doctype, rows, fallback):
	try:
		result = chat_json(
			[
				{
					"role": "system",
					"content": (
						"Answer the user's CRM question using only the supplied rows. "
						'Return JSON as {"answer":"..."}. Be concise, mention the '
						"number of supplied records, and never invent missing facts."
					),
				},
				{
					"role": "user",
					"content": json.dumps(
						{"question": question, "doctype": doctype, "rows": rows[:30]},
						default=str,
					)[:18000],
				},
			],
			purpose="Conversation",
		)
		return str(result.get("answer") or fallback)
	except Exception:
		return fallback


def _query_result(spec, settings, question):
	action = spec.get("action") or "query"
	max_limit = MAX_EXPORT_ROWS if action == "export" else MAX_LIMIT
	doctype, fields, filters, order_by, limit = _validate_query(spec, max_limit=max_limit)
	if not doctype:
		return None

	if action == "query":
		fetch_limit = min(limit, int(settings.ai_max_rows or 50))
	else:
		fetch_limit = min(limit, 10)
	rows = frappe.get_list(
		doctype,
		fields=fields,
		filters=filters,
		order_by=order_by,
		limit_page_length=fetch_limit,
	)
	fallback = str(spec.get("explanation") or _("Here is what I found."))
	answer = _summarize(question, doctype, rows, fallback) if spec.get("summarize") else fallback
	query = {
		"action": action,
		"doctype": doctype,
		"fields": fields,
		"filters": filters,
		"order_by": order_by,
		"limit": limit,
		"result_names": [row.name for row in rows if row.get("name")],
	}
	result = {
		"answer": answer,
		"doctype": doctype,
		"fields": fields,
		"rows": rows,
		"row_count": len(rows),
		"query": {"filters": filters, "order_by": order_by, "limit": limit},
	}
	if action == "export":
		result["export"] = {
			"doctype": doctype,
			"fields": fields,
			"filters": filters,
			"order_by": order_by,
			"limit": limit,
			"file_format": "Excel" if str(spec.get("file_format")).lower() == "excel" else "CSV",
		}
	return result, query


@frappe.whitelist()
def ask(question, session=None, credential=None):
	"""Plan and answer one chat turn using a browser-supplied credential."""
	question = str(question or "").strip()
	if not question:
		frappe.throw(_("Ask something."))

	context = _conversation_context(session)
	if session:
		_owned_session(session)
	else:
		session = _new_session(question).name

	_store_message(session, "user", question)
	messages = [
		{
			"role": "system",
			"content": SYSTEM.format(schema=_catalog(), today=frappe.utils.today()),
		},
		*context,
		{"role": "user", "content": question},
	]

	settings = frappe.get_cached_doc("Baton Settings")
	with use_client_credential(credential):
		spec = chat_json(messages, purpose="Conversation")
		action = str(spec.get("action") or ("query" if spec.get("doctype") else "help")).lower()
		spec["action"] = action

		if action in ("query", "export"):
			packed = _query_result(spec, settings, question)
			if packed:
				result, stored_spec = packed
				_store_message(
					session,
					"assistant",
					result["answer"],
					query_spec=stored_spec,
					row_count=result["row_count"],
				)
				log_action(
					f"chat.{action}",
					actor_type="AI_AGENT",
					reference_doctype=result["doctype"],
					input={"question": question},
					output={"rows": result["row_count"], "filters": result["query"]["filters"]},
					decision="ANSWER",
					reason=result["answer"][:400],
				)
				return {"session": session, **result}

		if action in WRITE_ACTIONS:
			plan, rows = _pending_action(spec)
			answer = _action_summary(plan)
			message = _store_message(
				session,
				"assistant",
				answer,
				query_spec=plan,
				row_count=len(rows),
			)
			plan["id"] = message.name
			log_action(
				"chat.action_proposed",
				actor_type="AI_AGENT",
				reference_doctype=plan["doctype"],
				input={"action": action, "names": plan.get("names", [])},
				decision="REQUIRE_CONFIRMATION",
				reason=plan.get("explanation") or answer,
			)
			return {
				"session": session,
				"answer": answer,
				"doctype": plan["doctype"],
				"fields": list(rows[0].keys()) if rows else [],
				"rows": rows,
				"row_count": len(rows),
				"query": None,
				"pending_action": plan,
			}

	answer = str(
		spec.get("explanation")
		or _(
			"I can find, summarize, export, create and update CRM records. I can also "
			"assign records, add comments and convert leads after you confirm the action."
		)
	)
	_store_message(session, "assistant", answer)
	return {
		"session": session,
		"answer": answer,
		"doctype": None,
		"fields": [],
		"rows": [],
		"row_count": 0,
		"query": None,
	}


def _execute_pending(plan):
	action = plan["action"]
	doctype = plan["doctype"]
	names = plan.get("names") or []
	results = []

	if action == "create":
		if not frappe.has_permission(doctype, ptype="create"):
			frappe.throw(_("You do not have permission to create {0}.").format(doctype))
		values = _clean_values(doctype, plan.get("values"))
		doc = frappe.get_doc({"doctype": doctype, **values}).insert()
		return [{"doctype": doctype, "name": doc.name}]

	if not names or len(names) > MAX_ACTION_ROWS:
		frappe.throw(_("The pending action has an invalid target list."))

	if action == "assign":
		from frappe.desk.form.assign_to import add as add_assignment

		assignee = _resolve_user(plan.get("assignee"))
		for name in names:
			frappe.get_doc(doctype, name).check_permission("write")
			add_assignment({"doctype": doctype, "name": name, "assign_to": [assignee]})
			results.append({"doctype": doctype, "name": name, "assigned_to": assignee})
		return results

	if action == "add_comment":
		from crm.api.comment import add_comment

		comment = str(plan.get("comment") or "").strip()
		if not comment:
			frappe.throw(_("A comment needs some text."))
		for name in names:
			frappe.get_doc(doctype, name).check_permission("read")
			created = add_comment(doctype, name, comment)
			results.append({"doctype": doctype, "name": name, "comment": created.name})
		return results

	if action == "convert_lead":
		from crm.fcrm.doctype.crm_lead.crm_lead import convert_to_deal

		for name in names:
			deal = convert_to_deal(lead=name)
			results.append({"doctype": "CRM Deal", "name": deal})
		return results

	if action == "update":
		values = _clean_values(doctype, plan.get("values"))
		for name in names:
			doc = frappe.get_doc(doctype, name)
			doc.check_permission("write")
			doc.update(values)
			doc.save()
			results.append({"doctype": doctype, "name": name, "fields": list(values)})
		return results

	frappe.throw(_("That pending action is not supported."))


@frappe.whitelist()
def execute_action(action_id, decision="confirm"):
	"""Confirm or cancel an action proposed by ``ask``; confirmations are idempotent."""
	# Serialize confirmations for this message. Without a row lock, two browser
	# retries can both observe "pending" and perform the same write twice.
	message = frappe.get_doc("Baton Chat Message", action_id, for_update=True)
	_owned_session(message.session)
	if message.role != "assistant" or not message.query_spec:
		frappe.throw(_("This is not a pending Ask Pulp action."))

	try:
		plan = json.loads(message.query_spec)
	except (TypeError, json.JSONDecodeError):
		frappe.throw(_("This pending action is invalid."))
	if plan.get("kind") != "pending_action":
		frappe.throw(_("This is not a pending Ask Pulp action."))

	if plan.get("status") == "completed":
		return {
			"status": "completed",
			"answer": message.content,
			"results": plan.get("results") or [],
		}
	if plan.get("status") == "cancelled":
		return {"status": "cancelled", "answer": message.content, "results": []}

	if str(decision).lower() != "confirm":
		plan["status"] = "cancelled"
		message.content = _("Cancelled. Nothing was changed.")
		message.query_spec = json.dumps(plan, indent=1, default=str)
		message.save(ignore_permissions=True)
		log_action(
			"chat.action_cancelled",
			actor_type="HUMAN",
			reference_doctype=plan.get("doctype"),
			input={"action": plan.get("action"), "names": plan.get("names", [])},
			decision="CANCEL",
		)
		return {"status": "cancelled", "answer": message.content, "results": []}

	results = _execute_pending(plan)
	plan["status"] = "completed"
	plan["results"] = results
	message.content = _("Done. {0} record(s) were processed successfully.").format(len(results))
	message.query_spec = json.dumps(plan, indent=1, default=str)
	message.row_count = len(results)
	message.save(ignore_permissions=True)
	log_action(
		f"chat.{plan['action']}",
		actor_type="HUMAN",
		reference_doctype=plan["doctype"],
		input={"names": plan.get("names", []), "fields": list((plan.get("values") or {}).keys())},
		output={"results": results},
		decision="CONFIRMED",
		reason=plan.get("explanation"),
	)
	return {"status": "completed", "answer": message.content, "results": results}


@frappe.whitelist()
def history(session):
	_owned_session(session)
	return frappe.get_all(
		"Baton Chat Message",
		filters={"session": session},
		fields=["name", "role", "content", "row_count", "query_spec", "creation"],
		order_by="creation asc",
	)
