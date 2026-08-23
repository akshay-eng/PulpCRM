"""Ask the CRM a question in English, get rows back.

Design note -- the model never writes SQL.

It returns a *query spec* (doctype, fields, filters, order, limit) which we
validate against an allowlist and then hand to `frappe.get_list`. That keeps
three properties that raw SQL would destroy:

  1. Row-level permissions still apply. `get_list` runs as the logged-in user,
     so a sales rep asking "show me all deals" sees only the deals they are
     allowed to see. Prompt injection cannot widen that.
  2. No writes are reachable. There is no code path from this module to an
     UPDATE or DELETE, regardless of what the model emits.
  3. Answers are reproducible. The spec is stored on the message, so any number
     can be traced back to the query that produced it.
"""

import json

import frappe
from frappe import _

from baton.audit import log_action
from baton.llm import chat_json, use_client_credential

# What the assistant is allowed to read. Everything else is invisible to it --
# including User, which would otherwise be an easy way to enumerate staff.
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

MAX_LIMIT = 200


def _catalog():
    """Field catalogue for the doctypes the assistant may read."""
    out = []
    for dt in ALLOWED_DOCTYPES:
        if not frappe.db.exists("DocType", dt):
            continue
        meta = frappe.get_meta(dt)
        fields = [
            f"{f.fieldname}:{f.fieldtype}"
            for f in meta.fields
            if f.fieldtype not in ("Section Break", "Column Break", "Tab Break", "HTML", "Table")
        ][:45]
        out.append(f"{dt} -> name, owner, creation, modified, " + ", ".join(fields))
    return "\n".join(out)


SYSTEM = """You turn a question about a CRM into a single JSON query spec.

Return ONLY a JSON object of this shape:
{{
  "doctype": "<one of the allowed doctypes>",
  "fields": ["fieldname", ...],
  "filters": {{"fieldname": value}} or {{"fieldname": ["operator", value]}},
  "order_by": "fieldname desc",
  "limit": <int>,
  "explanation": "<one sentence, what this query answers>"
}}

Rules:
- Use ONLY doctypes and fieldnames from the schema below. Never invent a field.
- Operators allowed: =, !=, >, <, >=, <=, like, not like, in, not in, between, is.
- For "recent" or "latest" use order_by on `modified desc` or `creation desc`.
- For date ranges use ["between", ["YYYY-MM-DD", "YYYY-MM-DD"]].
- Always include `name` in fields.
- For greetings or small talk, set doctype to null and reply helpfully in
  explanation, inviting the user to ask about their CRM data.
- If a request cannot be answered from this schema, set doctype to null and put
  a clear, friendly reason in explanation.

Schema:
{schema}

Today is {today}."""


def _validate(spec):
    dt = spec.get("doctype")
    if not dt:
        return None, [], {}, None, 0
    if dt not in ALLOWED_DOCTYPES:
        frappe.throw(_("The assistant may not read {0}.").format(dt))

    meta = frappe.get_meta(dt)
    valid = {f.fieldname for f in meta.fields} | {
        "name", "owner", "creation", "modified", "modified_by", "docstatus", "idx",
    }

    fields = [f for f in (spec.get("fields") or ["name"]) if f in valid] or ["name"]
    if "name" not in fields:
        fields.insert(0, "name")

    filters = {k: v for k, v in (spec.get("filters") or {}).items() if k in valid}

    order_by = spec.get("order_by") or "modified desc"
    if order_by.split()[0] not in valid:
        order_by = "modified desc"

    try:
        limit = min(int(spec.get("limit") or 20), MAX_LIMIT)
    except (TypeError, ValueError):
        limit = 20

    return dt, fields, filters, order_by, limit


@frappe.whitelist()
def ask(question, session=None, credential=None):
    """Answer `question` with real rows. Creates the session if absent."""
    question = (question or "").strip()
    if not question:
        frappe.throw(_("Ask something."))

    settings = frappe.get_cached_doc("Baton Settings")

    if not session:
        s = frappe.get_doc(
            {
                "doctype": "Baton Chat Session",
                "title": question[:110],
                "user": frappe.session.user,
            }
        ).insert(ignore_permissions=True)
        session = s.name

    frappe.get_doc(
        {"doctype": "Baton Chat Message", "session": session, "role": "user", "content": question}
    ).insert(ignore_permissions=True)

    with use_client_credential(credential):
        spec = chat_json(
            [
                {
                    "role": "system",
                    "content": SYSTEM.format(
                        schema=_catalog(), today=frappe.utils.today()
                    ),
                },
                {"role": "user", "content": question},
            ],
            purpose="Conversation",
        )

    doctype, fields, filters, order_by, limit = _validate(spec)

    if not doctype:
        answer = spec.get("explanation") or _(
            "I can help you explore your leads, deals, contacts, tasks, and CRM activity."
        )
        frappe.get_doc(
            {
                "doctype": "Baton Chat Message",
                "session": session,
                "role": "assistant",
                "content": answer,
                "row_count": 0,
            }
        ).insert(ignore_permissions=True)
        log_action(
            "chat.answer_without_query",
            actor_type="AI_AGENT",
            input={"question": question},
            decision="ANSWER",
            reason=answer[:400],
        )
        return {
            "session": session,
            "answer": answer,
            "doctype": None,
            "fields": [],
            "rows": [],
            "row_count": 0,
            "query": None,
        }

    # get_list, not get_all: this MUST run with the caller's permissions.
    rows = frappe.get_list(
        doctype,
        fields=fields,
        filters=filters,
        order_by=order_by,
        limit_page_length=min(limit, int(settings.ai_max_rows or 50)),
    )

    answer = spec.get("explanation") or _("Here is what I found.")

    frappe.get_doc(
        {
            "doctype": "Baton Chat Message",
            "session": session,
            "role": "assistant",
            "content": answer,
            "query_spec": json.dumps(
                {"doctype": doctype, "fields": fields, "filters": filters,
                 "order_by": order_by, "limit": limit},
                indent=1,
            ),
            "row_count": len(rows),
        }
    ).insert(ignore_permissions=True)

    log_action(
        "chat.query",
        actor_type="AI_AGENT",
        reference_doctype=doctype,
        input={"question": question},
        output={"rows": len(rows), "filters": filters},
        decision="ANSWER",
        reason=answer[:400],
    )

    return {
        "session": session,
        "answer": answer,
        "doctype": doctype,
        "fields": fields,
        "rows": rows,
        "row_count": len(rows),
        "query": {"filters": filters, "order_by": order_by, "limit": limit},
    }


@frappe.whitelist()
def history(session):
    return frappe.get_all(
        "Baton Chat Message",
        filters={"session": session},
        fields=["name", "role", "content", "row_count", "query_spec", "creation"],
        order_by="creation asc",
    )
