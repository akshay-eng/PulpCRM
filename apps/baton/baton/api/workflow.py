"""CRUD + catalogue for the workflow canvas in the CRM UI.

The canvas is the only client, so these return exactly the shapes it renders
rather than raw documents.
"""

import json

import frappe
from frappe import _

# Mirrors the grouping in the builder's action drawer. `node_type` must match a
# branch of baton.workflow.engine._execute.
ACTION_CATALOG = [
    {
        "group": "Data",
        "actions": [
            {"type": "Create Document", "label": "Create Record", "icon": "plus"},
            {"type": "Update Field", "label": "Update Record", "icon": "refresh-cw"},
            {"type": "Create Task", "label": "Create Task", "icon": "check-square"},
        ],
    },
    {
        "group": "AI",
        "actions": [{"type": "AI Agent", "label": "AI Agent", "icon": "sparkles"}],
    },
    {
        "group": "Flow",
        "actions": [
            {"type": "Condition", "label": "If / Else", "icon": "git-branch"},
            {"type": "Check Reply", "label": "Did they reply?", "icon": "message-square"},
            {"type": "Wait", "label": "Delay", "icon": "pause"},
        ],
    },
    {
        "group": "Core",
        "actions": [
            {"type": "Send Email", "label": "Send Email", "icon": "send"},
            {"type": "Webhook", "label": "HTTP Request", "icon": "globe"},
        ],
    },
    {
        "group": "Human Input",
        "actions": [
            {"type": "Request Approval", "label": "Request Approval", "icon": "check-square"}
        ],
    },
    {
        "group": "Baton",
        "actions": [
            {"type": "Send WhatsApp", "label": "Send WhatsApp Message", "icon": "message-circle"}
        ],
    },
]


@frappe.whitelist()
def get_action_catalog():
    return ACTION_CATALOG


@frappe.whitelist()
def get_workflows():
    return frappe.get_all(
        "Baton Workflow",
        fields=["name", "workflow_name", "enabled", "trigger_type", "trigger_doctype",
                "trigger_event", "modified"],
        order_by="modified desc",
    )


@frappe.whitelist()
def get_workflow(name):
    doc = frappe.get_doc("Baton Workflow", name)
    doc.check_permission("read")
    return {
        "name": doc.name,
        "workflow_name": doc.workflow_name,
        "enabled": doc.enabled,
        "trigger_type": doc.trigger_type,
        "trigger_doctype": doc.trigger_doctype,
        "trigger_event": doc.trigger_event,
        "cron": doc.cron,
        "condition": doc.condition,
        "nodes": [
            {
                "node_id": n.node_id,
                "node_type": n.node_type,
                "label": n.label,
                "next_node": n.next_node,
                "next_node_alt": n.next_node_alt,
                "config": json.loads(n.config) if n.config else {},
                "position_x": n.position_x or 0,
                "position_y": n.position_y or 0,
            }
            for n in doc.nodes
        ],
    }


@frappe.whitelist()
def save_workflow(data):
    """Create or update from the canvas. `data` is the JSON the builder holds."""
    if isinstance(data, str):
        data = json.loads(data)

    name = data.get("name")
    if name and frappe.db.exists("Baton Workflow", name):
        doc = frappe.get_doc("Baton Workflow", name)
        doc.check_permission("write")
    else:
        doc = frappe.new_doc("Baton Workflow")

    doc.workflow_name = data.get("workflow_name") or "Untitled workflow"
    doc.enabled = 1 if data.get("enabled") else 0
    doc.trigger_type = data.get("trigger_type") or "Manual"
    doc.trigger_doctype = data.get("trigger_doctype")
    doc.trigger_event = data.get("trigger_event")
    doc.cron = data.get("cron")
    doc.condition = data.get("condition")

    doc.set("nodes", [])
    for n in data.get("nodes") or []:
        doc.append(
            "nodes",
            {
                "node_id": n.get("node_id"),
                "node_type": n.get("node_type"),
                "label": n.get("label"),
                "next_node": n.get("next_node"),
                "next_node_alt": n.get("next_node_alt"),
                "config": json.dumps(n.get("config") or {}),
                "position_x": n.get("position_x") or 0,
                "position_y": n.get("position_y") or 0,
            },
        )

    doc.save()
    frappe.db.commit()
    return get_workflow(doc.name)


@frappe.whitelist()
def delete_workflow(name):
    frappe.delete_doc("Baton Workflow", name)
    frappe.db.commit()
    return True


@frappe.whitelist()
def set_enabled(name, enabled):
    doc = frappe.get_doc("Baton Workflow", name)
    doc.check_permission("write")
    doc.enabled = 1 if str(enabled) in ("1", "true", "True") else 0
    doc.save()
    frappe.db.commit()
    return doc.enabled


@frappe.whitelist()
def test_run(name, reference_doctype=None, reference_name=None):
    from baton.workflow.engine import run_workflow

    doc = None
    if reference_doctype and reference_name:
        doc = frappe.get_doc(reference_doctype, reference_name)
    elif frappe.db.exists("Baton Workflow", name):
        # Test with the newest record of the trigger doctype, so a manual test
        # exercises the same shape a real trigger would.
        wf = frappe.get_doc("Baton Workflow", name)
        if wf.trigger_doctype:
            latest = frappe.get_all(wf.trigger_doctype, limit=1, order_by="modified desc", pluck="name")
            if latest:
                doc = frappe.get_doc(wf.trigger_doctype, latest[0])

    # A test must run even when the workflow is switched off.
    was_enabled = frappe.db.get_value("Baton Workflow", name, "enabled")
    if not was_enabled:
        frappe.db.set_value("Baton Workflow", name, "enabled", 1)
        frappe.db.commit()
    try:
        run_name = run_workflow(name, doc=doc, run_reason="test")
    finally:
        if not was_enabled:
            frappe.db.set_value("Baton Workflow", name, "enabled", 0)
            frappe.db.commit()

    if not run_name:
        return {"ok": False, "message": _("Workflow condition did not match; nothing ran.")}
    return {"ok": True, "run": get_run(run_name)}


@frappe.whitelist()
def get_runs(workflow=None, limit=50):
    filters = {"workflow": workflow} if workflow else {}
    return frappe.get_all(
        "Baton Workflow Run",
        filters=filters,
        fields=["name", "workflow", "status", "reference_doctype", "reference_name", "creation"],
        order_by="creation desc",
        limit_page_length=limit,
    )


@frappe.whitelist()
def get_run(name):
    doc = frappe.get_doc("Baton Workflow Run", name)
    return {
        "name": doc.name,
        "workflow": doc.workflow,
        "status": doc.status,
        "error": doc.error,
        "reference_doctype": doc.reference_doctype,
        "reference_name": doc.reference_name,
        "creation": doc.creation,
        "steps": [
            {
                "node_id": s.node_id,
                "node_type": s.node_type,
                "status": s.status,
                "duration_ms": s.duration_ms,
                "output": s.output,
            }
            for s in doc.steps
        ],
    }
