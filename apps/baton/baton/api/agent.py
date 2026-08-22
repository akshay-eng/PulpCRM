"""CRUD for agent definitions, plus a dry run.

Kept separate from api/workflow.py because an agent is a definition the whole
app can reference, not part of any one graph.
"""

import json

import frappe
from frappe import _

FIELDS = (
    "agent_name", "enabled", "purpose", "channel", "goal", "persona",
    "business_context", "guardrails", "max_turns", "max_reprompts",
    "reply_timeout_hours", "transcript_limit",
)


@frappe.whitelist()
def get_agents():
    return frappe.get_all(
        "Baton Agent", fields=["name", "agent_name", "enabled", "goal"],
        order_by="agent_name",
    )


@frappe.whitelist()
def get_agent(name):
    doc = frappe.get_doc("Baton Agent", name)
    doc.check_permission("read")
    out = {f: doc.get(f) for f in FIELDS}
    out["name"] = doc.name
    out["options"] = [
        {"key": o.key, "label": o.label, "description": o.description,
         "synonyms": o.synonyms}
        for o in doc.options
    ]
    out["outcomes"] = [
        {"key": o.key, "label": o.label, "required": o.required,
         "target_doctype": o.target_doctype, "target_field": o.target_field}
        for o in doc.outcomes
    ]
    return out


@frappe.whitelist()
def save_agent(data):
    frappe.only_for(["System Manager", "Sales Manager"])
    if isinstance(data, str):
        data = json.loads(data)

    name = data.get("name")
    if name and frappe.db.exists("Baton Agent", name):
        doc = frappe.get_doc("Baton Agent", name)
        doc.check_permission("write")
    else:
        doc = frappe.new_doc("Baton Agent")
        data["agent_name"] = _unique(data.get("agent_name") or "New agent")

    for f in FIELDS:
        if f in data:
            doc.set(f, data[f])

    # Keys are what the model returns, so a blank one would silently accept
    # anything. Drop incomplete rows rather than storing a trap.
    doc.set("options", [])
    for o in data.get("options") or []:
        if o.get("key"):
            doc.append("options", {
                "key": o["key"].strip(), "label": o.get("label") or o["key"],
                "description": o.get("description"), "synonyms": o.get("synonyms"),
            })

    doc.set("outcomes", [])
    for o in data.get("outcomes") or []:
        if o.get("key"):
            doc.append("outcomes", {
                "key": o["key"].strip(), "label": o.get("label") or o["key"],
                "required": 1 if o.get("required") else 0,
                "target_doctype": o.get("target_doctype"),
                "target_field": o.get("target_field"),
            })

    doc.save()
    frappe.db.commit()
    return get_agent(doc.name)


def _unique(wanted):
    if not frappe.db.exists("Baton Agent", wanted):
        return wanted
    for i in range(2, 200):
        candidate = f"{wanted} {i}"
        if not frappe.db.exists("Baton Agent", candidate):
            return candidate
    return f"{wanted} {frappe.generate_hash(length=6)}"


@frappe.whitelist()
def delete_agent(name):
    frappe.only_for(["System Manager", "Sales Manager"])
    frappe.delete_doc("Baton Agent", name)
    frappe.db.commit()
    return True


@frappe.whitelist()
def test_agent(name, reference_doctype=None, reference_name=None):
    """Ask what it would say next. Sends nothing.

    Defaults to the most recently touched lead, so the button works before
    anyone has wired the agent into a workflow.
    """
    frappe.only_for(["System Manager", "Sales Manager"])
    from baton.agents.conversation import decide

    if not reference_name:
        reference_doctype = "CRM Lead"
        latest = frappe.get_all("CRM Lead", limit=1, order_by="modified desc", pluck="name")
        if not latest:
            frappe.throw(_("Create a lead first — the test runs against a real record."))
        reference_name = latest[0]

    return decide(name, reference_doctype, reference_name)
