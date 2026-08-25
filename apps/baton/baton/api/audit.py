"""Permission-aware, user-facing access to Pulp's record history."""

import json

import frappe
from frappe import _
from frappe.utils import cint

from baton.audit import AUDITED_DOCTYPES


def _json(value, fallback):
	try:
		return json.loads(value) if value else fallback
	except (TypeError, json.JSONDecodeError):
		return fallback


def _can_read(row):
	doctype = row.reference_doctype
	name = row.reference_name
	if doctype not in AUDITED_DOCTYPES:
		return False
	if frappe.db.exists(doctype, name):
		return frappe.has_permission(doctype, "read", name)
	# A deleted record no longer has a row against which permissions can be
	# evaluated. Managers may inspect it; its own actor may still see the action
	# they performed. Nobody else gets a deleted-record metadata leak.
	return row.actor_id == frappe.session.user or bool(
		{"System Manager", "Sales Manager"} & set(frappe.get_roles())
	)


@frappe.whitelist()
def get_audit_trail(reference_doctype=None, reference_name=None, start=0, limit=50):
	"""Return recent record mutations after checking each referenced record."""
	if reference_doctype and reference_doctype not in AUDITED_DOCTYPES:
		frappe.throw(_("Audit history is not available for {0}.").format(reference_doctype))
	if reference_name and not reference_doctype:
		frappe.throw(_("Choose a record type before choosing a record."))

	start = max(cint(start), 0)
	limit = max(1, min(cint(limit) or 50, 100))
	filters = {"action": ["like", "record.%"]}
	if reference_doctype:
		filters["reference_doctype"] = reference_doctype
	if reference_name:
		filters["reference_name"] = reference_name

	# Permission filtering happens per referenced record. Fetching a larger
	# window prevents one inaccessible team's rows from producing an empty page.
	rows = frappe.get_all(
		"Baton Action Log",
		filters=filters,
		fields=[
			"name",
			"action",
			"actor_type",
			"actor_id",
			"reference_doctype",
			"reference_name",
			"workflow",
			"workflow_run",
			"node_id",
			"bot",
			"input",
			"output",
			"decision",
			"reason",
			"creation",
		],
		order_by="creation desc",
		start=start,
		limit_page_length=limit * 4,
		ignore_permissions=True,
	)

	entries = []
	for row in rows:
		if not _can_read(row):
			continue
		payload = _json(row.input, {})
		metadata = _json(row.output, {})
		entries.append(
			{
				"name": row.name,
				"event": row.action.removeprefix("record."),
				"actor_type": row.actor_type,
				"actor_id": row.actor_id,
				"reference_doctype": row.reference_doctype,
				"reference_name": row.reference_name,
				"title": metadata.get("title") or row.reference_name,
				"source": metadata.get("source") or "System",
				"danger_mode": bool(metadata.get("danger_mode")),
				"changes": payload.get("changes") or [],
				"reason": row.reason,
				"workflow": row.workflow,
				"workflow_run": row.workflow_run,
				"node_id": row.node_id,
				"bot": row.bot,
				"creation": row.creation,
			}
		)
		if len(entries) >= limit:
			break

	return {
		"entries": entries,
		"next_start": start + len(rows),
		"has_more": len(rows) == limit * 4,
		"doctypes": [doctype for doctype in AUDITED_DOCTYPES if frappe.db.exists("DocType", doctype)],
	}
