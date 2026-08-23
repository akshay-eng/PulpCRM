"""CRUD + catalogue for the workflow canvas in the CRM UI.

The canvas is the only client, so these return exactly the shapes it renders
rather than raw documents.
"""

import json

import frappe
from frappe import _

from baton.workflow.validate import errors_only, validate_graph

# Mirrors the grouping in the builder's action drawer. `node_type` must match a
# branch of baton.workflow.engine._execute.
# The palette, grouped the way a salesperson thinks: by the thing being acted
# on, not by the machinery underneath. Several entries share one `type` and
# differ only in `config` -- "Move the deal to a stage" is an Update Record with
# the doctype and field already chosen. A preset is not a shortcut for us, it is
# the difference between a builder that assumes you know the schema and one that
# does not.
ACTION_CATALOG = [
    {
        "group": "Leads",
        "actions": [
            {"type": "Update Field", "label": "Update the lead", "icon": "refresh-cw",
             "doctype": "CRM Lead",
             "help": "Change a field on the lead that started this."},
            {"type": "Update Field", "label": "Set the lead status", "icon": "flag",
             "doctype": "CRM Lead", "config": {"field": "status"},
             "help": "Move it to New, Contacted, Qualified and so on."},
            {"type": "Assign To", "label": "Assign the lead", "icon": "user-check",
             "doctype": "CRM Lead",
             "help": "Put it on someone's list and notify them."},
            {"type": "Add Comment", "label": "Comment on the lead", "icon": "message-square-text",
             "doctype": "CRM Lead",
             "help": "Leave a note in the activity feed."},
            {"type": "Convert Lead", "label": "Convert to a deal", "icon": "arrow-right-left",
             "doctype": "CRM Lead",
             "help": "Creates the contact, the organization and the deal."},
        ],
    },
    {
        "group": "Deals",
        "actions": [
            {"type": "Update Field", "label": "Update the deal", "icon": "refresh-cw",
             "doctype": "CRM Deal",
             "help": "Change a field on the deal this ran on."},
            {"type": "Update Field", "label": "Move the deal to a stage", "icon": "flag",
             "doctype": "CRM Deal", "config": {"field": "status"},
             "help": "Qualification, Demo, Negotiation and so on."},
            {"type": "Assign To", "label": "Assign the deal", "icon": "user-check",
             "doctype": "CRM Deal",
             "help": "Put it on someone's list and notify them."},
            {"type": "Add Comment", "label": "Comment on the deal", "icon": "message-square-text",
             "doctype": "CRM Deal",
             "help": "Leave a note in the activity feed."},
            {"type": "Create Document", "label": "Create a deal", "icon": "plus",
             "config": {"doctype": "CRM Deal"},
             "help": "A brand new deal, with the fields you set."},
        ],
    },
    {
        "group": "Contacts & organizations",
        "actions": [
            {"type": "Create Document", "label": "Create a contact", "icon": "plus",
             "config": {"doctype": "Contact"},
             "help": "A new person record."},
            {"type": "Create Document", "label": "Create an organization", "icon": "plus",
             "config": {"doctype": "CRM Organization"},
             "help": "A new company record."},
            {"type": "Update Field", "label": "Update the organization", "icon": "refresh-cw",
             "doctype": "CRM Organization",
             "help": "Change a field on the organization this ran on."},
        ],
    },
    {
        "group": "Tasks & notes",
        "actions": [
            {"type": "Create Task", "label": "Create a task", "icon": "check-circle",
             "help": "Give a person something to do, linked to the record."},
            {"type": "Create Note", "label": "Write a note", "icon": "sticky-note",
             "help": "Attach a note to the record."},
            {"type": "Request Approval", "label": "Ask a person to approve", "icon": "check-square",
             "help": "Pauses here until someone says yes or no."},
        ],
    },
    {
        "group": "Messaging",
        "actions": [
            {"type": "Send WhatsApp", "label": "Send a WhatsApp message",
             "icon": "message-circle",
             "help": "Goes through approval, quiet hours and handoff rules."},
            {"type": "Send Email", "label": "Send an email", "icon": "send",
             "help": "To the address on the record, or one you name."},
            {"type": "Await Reply", "label": "Wait for their reply",
             "icon": "message-square-dot",
             "help": "Pauses until they answer, or until the deadline you set."},
            {"type": "Check Reply", "label": "Have they replied?", "icon": "message-square",
             "help": "Branches on whether they answered since we last wrote."},
        ],
    },
    {
        "group": "AI",
        "actions": [
            {"type": "AI Conversation", "label": "Let an agent talk to them", "icon": "bot",
             "help": "A scripted agent narrows something down over several turns."},
            {"type": "AI Agent", "label": "Ask the model", "icon": "sparkles",
             "help": "Gets an answer for the workflow. Sends nothing to anyone."},
        ],
    },
    {
        "group": "Scheduling",
        "actions": [
            {"type": "Offer Slots", "label": "Offer meeting times", "icon": "calendar-clock",
             "help": "Sends free times and waits for them to pick a number."},
            {"type": "Book Appointment", "label": "Book the meeting", "icon": "calendar-check",
             "help": "Turns the time they picked into a calendar event."},
        ],
    },
    {
        "group": "Flow",
        "actions": [
            {"type": "Condition", "label": "If / else", "icon": "git-branch",
             "help": "Splits the path on a rule you build."},
            {"type": "Wait", "label": "Wait a while", "icon": "pause",
             "help": "Pauses for minutes, hours or days, then carries on."},
            {"type": "Webhook", "label": "Call a URL", "icon": "globe",
             "help": "Posts to another system."},
        ],
    },
]


# The doctypes a workflow may touch. Deliberately not "any doctype": this is a
# CRM automation builder, and letting it write to User or Email Account turns it
# into something with a much larger blast radius than anyone asked for.
BUILDER_DOCTYPES = [
    "CRM Lead", "CRM Deal", "CRM Task", "Contact", "CRM Organization",
    "CRM Call Log", "FCRM Note",
]

# What each node type accepts, declared once here so the canvas renders forms
# from it rather than each side keeping its own copy. Field types map to
# frappe-ui controls: text, textarea, select, int, check, doctype, code.
NODE_SCHEMAS = {
    "Trigger": [],
    "Condition": [
        # A no-code builder cannot require a Python expression for its main
        # branching primitive. The picker builds the expression; `expression`
        # stays as the escape hatch for people who want one.
        {"field": "rules", "label": "Continue when", "type": "rules",
         "help": "All of these must be true."},
        {"field": "expression", "label": "…or write it yourself", "type": "code",
         "placeholder": "doc.status == 'Open'",
         "help": "Python over doc, payload and vars. Overrides the rules above."},
    ],
    "Update Field": [
        # A field *picker*, not a text box. Typing "staus" into a text box saves
        # cleanly, runs, and silently writes nothing -- the single most common
        # way a no-code automation looks fine and does nothing.
        {"field": "field", "label": "Field", "type": "field", "required": True,
         "help": "Fields of the record this workflow runs on."},
        {"field": "value", "label": "New value", "type": "fieldvalue",
         "help": "Supports {{ doc.fieldname }} to copy from the record."},
    ],
    "Create Document": [
        {"field": "doctype", "label": "Record type", "type": "doctype", "required": True},
        {"field": "values", "label": "Values", "type": "keyvalue", "value_of": "doctype",
         "help": "Pick a field, give it a value. {{ doc.fieldname }} works here too."},
    ],
    "Send WhatsApp": [
        {"field": "to", "label": "To", "type": "text",
         "placeholder": "{{ doc.mobile_no }}",
         "help": "Blank uses the record's mobile number."},
        {"field": "message", "label": "Message", "type": "textarea", "required": True,
         "placeholder": "Hi {{ doc.lead_name }}, thanks for your interest."},
        {"field": "author", "label": "Attributed to", "type": "select",
         "options": ["ai", "human"], "default": "ai",
         "help": "ai means a human reply pauses automation on this conversation."},
    ],
    "Send Email": [
        {"field": "to", "label": "To", "type": "text", "required": True,
         "placeholder": "{{ doc.email }}"},
        {"field": "subject", "label": "Subject", "type": "text"},
        {"field": "message", "label": "Message", "type": "textarea"},
    ],
    "AI Conversation": [
        {"field": "agent", "label": "Agent", "type": "agent", "required": True,
         "help": "Defined under Settings > AI Agents."},
        {"field": "to", "label": "To", "type": "text",
         "placeholder": "{{ doc.mobile_no }}",
         "help": "Blank uses the record's mobile number."},
    ],
    "AI Agent": [
        {"field": "prompt", "label": "Prompt", "type": "textarea", "required": True,
         "help": "The reply is stored on the run step. It is not sent to anyone."},
        {"field": "purpose", "label": "Model purpose", "type": "text",
         "placeholder": "Workflow"},
    ],
    "Wait": [
        {"field": "amount", "label": "Wait", "type": "int", "default": 1},
        {"field": "unit", "label": "Unit", "type": "select",
         "options": ["minutes", "hours", "days"], "default": "hours"},
    ],
    "Await Reply": [
        {"field": "channel", "label": "On channel", "type": "select",
         "options": ["WhatsApp", "Email", "Any"], "default": "WhatsApp"},
        {"field": "timeout_hours", "label": "Give up after (hours)", "type": "int", "default": 24,
         "help": "On timeout the run takes the red branch."},
    ],
    "Request Approval": [
        {"field": "kind", "label": "Kind", "type": "select",
         "options": ["Send Message", "Other"], "default": "Other"},
        {"field": "draft", "label": "What to approve", "type": "textarea"},
        {"field": "timeout_hours", "label": "Expire after (hours)", "type": "int", "default": 48},
    ],
    "Webhook": [
        {"field": "url", "label": "URL", "type": "text", "required": True,
         "placeholder": "https://example.com/hook"},
        {"field": "body", "label": "Send this", "type": "keyvalue",
         "help": "Name and value pairs. {{ doc.fieldname }} works in values."},
    ],
    "Assign To": [
        # Not required: the engine falls back to the record's owner, and marking
        # it required while the help text says "leave blank" is the kind of
        # contradiction that makes people distrust the whole form.
        {"field": "assign_to", "label": "Assign to", "type": "user",
         "help": "Blank uses the record's own owner."},
        {"field": "description", "label": "Why", "type": "text",
         "placeholder": "Follow up with {{ doc.lead_name }}"},
    ],
    "Add Comment": [
        {"field": "comment", "label": "Comment", "type": "textarea", "required": True,
         "placeholder": "Automatically qualified: {{ doc.status }}"},
    ],
    "Create Note": [
        {"field": "title", "label": "Title", "type": "text"},
        {"field": "content", "label": "Note", "type": "textarea", "required": True},
    ],
    "Convert Lead": [
        {"field": "note", "label": "Note", "type": "text",
         "help": "Creates the contact, the organization and the deal from this lead."},
    ],
    "Offer Slots": [
        {"field": "service", "label": "Service", "type": "service",
         "help": "Sets the meeting length. Leave blank to use the duration below."},
        {"field": "duration", "label": "Length (minutes)", "type": "int", "default": 30},
        {"field": "count", "label": "How many to offer", "type": "int", "default": 3},
        {"field": "availability", "label": "Availability", "type": "availability",
         "help": "Blank picks the record owner's schedule, then the shared one."},
        {"field": "message", "label": "Lead-in", "type": "textarea",
         "placeholder": "When suits you? Reply with a number."},
        {"field": "timeout_hours", "label": "Give up after (hours)", "type": "int", "default": 24},
    ],
    "Book Appointment": [
        {"field": "subject", "label": "Meeting title", "type": "text",
         "placeholder": "Call with {{ doc.lead_name }}"},
        {"field": "description", "label": "Notes", "type": "textarea"},
        {"field": "confirmation", "label": "Confirmation message", "type": "textarea",
         "placeholder": "Booked — see you then."},
        {"field": "add_video", "label": "Add a video link", "type": "check"},
    ],
    "Check Reply": [
        {"field": "channel", "label": "On channel", "type": "select",
         "options": ["Any", "WhatsApp", "Email"], "default": "Any",
         "help": "Green branch if they have answered since our last message, "
                 "red branch if they have not."},
    ],
    "Create Task": [
        {"field": "subject", "label": "Title", "type": "text", "required": True,
         "placeholder": "Follow up with {{ doc.lead_name }}"},
        {"field": "description", "label": "Description", "type": "textarea"},
        {"field": "priority", "label": "Priority", "type": "select",
         "options": ["Low", "Medium", "High"], "default": "Medium"},
        {"field": "owner", "label": "Assign to", "type": "user",
         "help": "Blank assigns to whoever triggered the run."},
    ],
}


# Shown on every node under "If it fails". These are stored columns on
# Baton Workflow Node rather than config keys, so the form posts them alongside
# config -- but a user could not reach them at all before, which made the retry
# and fallback machinery unreachable from the product that owns it.
ERROR_SCHEMA = [
    {"field": "on_error", "label": "If this step fails", "type": "select",
     "options": ["Fail run", "Continue", "Go to fallback"], "default": "Fail run",
     "stored": True},
    {"field": "max_retries", "label": "Retry this many times", "type": "int",
     "default": 0, "stored": True},
    {"field": "retry_delay", "label": "Wait between retries (s)", "type": "int",
     "default": 30, "stored": True},
    {"field": "fallback_node", "label": "Go to this step instead", "type": "node",
     "depends_on": "on_error", "depends_value": "Go to fallback", "stored": True},
]


# Node types that fork, and what each branch means.
#
# Only `Condition` used to draw a second handle, so every other forking node --
# a conversation that timed out, an approval that was rejected, slots nobody
# picked -- had an alternate branch the canvas could not draw, connect or
# delete. The branch existed and ran; it was simply invisible.
BRANCH_LABELS = {
    "Condition": ["yes", "no"],
    "Check Reply": ["replied", "no reply"],
    "Await Reply": ["replied", "timed out"],
    "AI Conversation": ["done", "handed over"],
    "Offer Slots": ["picked one", "no answer"],
    "Book Appointment": ["booked", "could not book"],
    "Request Approval": ["approved", "rejected"],
    "Convert Lead": ["converted", "could not"],
}


@frappe.whitelist()
def get_node_schemas():
    """What each node type accepts, so the canvas can render real forms.

    Server-owned on purpose: the builder should never need updating because a
    node grew a new option, and nothing here may leak a credential.
    """
    agents = frappe.get_all("Baton Agent", filters={"enabled": 1}, pluck="name") \
        if frappe.db.table_exists("Baton Agent") else []
    services = frappe.get_all("Baton Service", filters={"enabled": 1}, pluck="name") \
        if frappe.db.table_exists("Baton Service") else []
    availabilities = frappe.get_all("Baton Availability", filters={"enabled": 1}, pluck="name") \
        if frappe.db.table_exists("Baton Availability") else []
    users = frappe.get_all("User", filters={"enabled": 1, "user_type": "System User"},
                           fields=["name", "full_name"], order_by="full_name",
                           limit_page_length=200)

    return {"schemas": NODE_SCHEMAS, "doctypes": BUILDER_DOCTYPES, "agents": agents,
            "services": services, "availabilities": availabilities,
            "users": users, "error_schema": ERROR_SCHEMA,
            "branch_labels": BRANCH_LABELS}


# Link targets small enough to offer as a list. CRM's own status/source/industry
# tables are a handful of rows each; User is not, and neither is anything the
# user has thousands of.
LINK_OPTION_LIMIT = 60


def _link_values(target):
    """The choices behind a Link field, when there are few enough to show."""
    if not target or not frappe.db.table_exists(target):
        return []
    try:
        count = frappe.db.count(target)
        if not count or count > LINK_OPTION_LIMIT:
            return []
        return frappe.get_all(target, pluck="name", order_by="name",
                              limit_page_length=LINK_OPTION_LIMIT)
    except Exception:
        return []


@frappe.whitelist()
def get_fields(doctype):
    """Comparable fields on a doctype, for the field and value pickers.

    Link fields carry their choices too. In Frappe CRM `status`, `source`,
    `industry` and `territory` are all Links rather than Selects, so offering
    options only for Selects meant the most-edited fields in the product fell
    back to a free-text box -- where "qualified" saves cleanly and then does
    nothing, because the value is "Qualified".
    """
    if doctype not in BUILDER_DOCTYPES:
        return []
    meta = frappe.get_meta(doctype)
    skip = ("Section Break", "Column Break", "Tab Break", "HTML", "Table",
            "Table MultiSelect", "Button", "Heading")

    out = []
    for f in meta.fields:
        if f.fieldtype in skip:
            continue
        if f.fieldtype == "Select":
            options = [o for o in (f.options or "").split("\n") if o]
        elif f.fieldtype == "Link":
            options = _link_values(f.options)
        elif f.fieldtype == "Check":
            options = ["0", "1"]
        else:
            options = []
        out.append({"field": f.fieldname, "label": f.label or f.fieldname,
                    "type": f.fieldtype, "options": options})

    out += [{"field": x, "label": x, "type": "Data", "options": []}
            for x in ("name", "owner", "creation", "modified")]
    return out


@frappe.whitelist()
def get_operators():
    """Operators the engine actually implements, so the UI cannot offer more."""
    from baton.workflow.engine import RULE_OPERATORS

    return sorted(RULE_OPERATORS)


@frappe.whitelist()
def get_event_catalog():
    """Event names an Event trigger may subscribe to."""
    from baton.events import EVENTS

    # workflow.* would let a workflow trigger itself; observability, not a hook.
    return sorted(e for e in EVENTS if not e.startswith("workflow."))


@frappe.whitelist()
def get_action_catalog():
    return ACTION_CATALOG


@frappe.whitelist()
def get_workflows():
    rows = frappe.get_all(
        "Baton Workflow",
        fields=["name", "workflow_name", "kind", "enabled", "description", "modified"],
        order_by="modified desc",
    )
    if not rows:
        return rows

    # One query for every workflow's triggers, rather than one per row.
    triggers = frappe.get_all(
        "Baton Workflow Trigger",
        filters={"parenttype": "Baton Workflow",
                 "parent": ["in", [r.name for r in rows]]},
        fields=["parent", "trigger_type", "trigger_doctype", "trigger_event", "cron",
                "event_name"],
    )
    by_parent = {}
    for t in triggers:
        by_parent.setdefault(t.parent, []).append(t)

    for r in rows:
        mine = by_parent.get(r.name, [])
        r.trigger_count = len(mine)
        r.trigger_summary = _describe_trigger(mine[0]) if mine else ""
    return rows


def _describe_trigger(t):
    if t.trigger_type == "Document Event":
        return f"{t.trigger_doctype} · {t.trigger_event}"
    if t.trigger_type == "Scheduled":
        return f"Schedule · {t.cron}"
    if t.trigger_type == "Event":
        return f"Event · {t.event_name}"
    return t.trigger_type or ""


@frappe.whitelist()
def get_workflow(name):
    doc = frappe.get_doc("Baton Workflow", name)
    doc.check_permission("read")
    return {
        "name": doc.name,
        "workflow_name": doc.workflow_name,
        "kind": doc.get("kind") or "Workflow",
        "description": doc.get("description"),
        "enabled": doc.enabled,
        "trigger_type": doc.trigger_type,
        "trigger_doctype": doc.trigger_doctype,
        "trigger_event": doc.trigger_event,
        "cron": doc.cron,
        "condition": doc.condition,
        "trigger_event_name": doc.trigger_event_name,
        "triggers": [
            {
                "enabled": t.enabled,
                "trigger_type": t.trigger_type,
                "trigger_doctype": t.trigger_doctype,
                "trigger_event": t.trigger_event,
                "field_changed": t.field_changed,
                "cron": t.cron,
                "event_name": t.event_name,
                "webhook_path": t.webhook_path,
                "condition": t.condition,
            }
            for t in doc.get("triggers") or []
        ],
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
                "save_as": n.save_as,
                # Round-tripped so the builder cannot silently discard a retry
                # policy set in Desk. See save_workflow.
                "max_retries": n.max_retries or 0,
                "retry_delay": n.retry_delay or 30,
                "on_error": n.on_error or "Fail run",
                "fallback_node": n.fallback_node,
            }
            for n in doc.nodes
        ],
    }


def _unique_name(wanted):
    if not frappe.db.exists("Baton Workflow", wanted):
        return wanted
    for i in range(2, 200):
        candidate = f"{wanted} {i}"
        if not frappe.db.exists("Baton Workflow", candidate):
            return candidate
    return f"{wanted} {frappe.generate_hash(length=6)}"


def _save_triggers(doc, triggers):
    """Rebuild the triggers table, keeping generated webhook paths stable.

    A webhook path is an address someone has already configured on the far end,
    so regenerating it on every save would silently break every caller.
    """
    if triggers is None:
        return

    existing_paths = {
        (t.trigger_type, t.trigger_doctype, t.trigger_event, t.cron, t.event_name): t.webhook_path
        for t in doc.get("triggers") or []
        if t.webhook_path
    }

    doc.set("triggers", [])
    for t in triggers:
        key = (t.get("trigger_type"), t.get("trigger_doctype"),
               t.get("trigger_event"), t.get("cron"), t.get("event_name"))
        path = t.get("webhook_path") or existing_paths.get(key)
        secret = t.get("webhook_secret")
        if t.get("trigger_type") == "Webhook" and not path:
            path = frappe.generate_hash(length=24)
            # Generated with the path, because the endpoint fails closed without
            # one -- a trigger that silently accepts nothing is worse than no
            # trigger at all.
            secret = frappe.generate_hash(length=32)

        doc.append("triggers", {
            "enabled": 1 if t.get("enabled", 1) else 0,
            "trigger_type": t.get("trigger_type"),
            "trigger_doctype": t.get("trigger_doctype"),
            "trigger_event": t.get("trigger_event"),
            "field_changed": t.get("field_changed"),
            "cron": t.get("cron"),
            "event_name": t.get("event_name"),
            "webhook_path": path,
            "webhook_secret": secret,
            "condition": t.get("condition"),
        })


@frappe.whitelist()
def validate_workflow(data):
    """Check a graph without saving it. The canvas calls this as you build."""
    if isinstance(data, str):
        data = json.loads(data)
    return validate_graph(data.get("nodes") or [], data.get("triggers"),
                          kind=data.get("kind") or "Workflow")


@frappe.whitelist()
def save_workflow(data):
    """Create or update from the canvas. `data` is the JSON the builder holds."""
    if isinstance(data, str):
        data = json.loads(data)

    # Refuse to persist a graph that cannot run. Warnings are fine to save --
    # a half-wired graph is a normal state while you are still building it.
    blocking = errors_only(validate_graph(
        data.get("nodes") or [], data.get("triggers"),
        kind=data.get("kind") or "Workflow"))
    if blocking:
        frappe.throw(
            _("This workflow cannot be saved yet:") + "\n"
            + "\n".join(f"- {i['message']}" for i in blocking),
            title=_("Invalid workflow"),
        )

    name = data.get("name")
    if name and frappe.db.exists("Baton Workflow", name):
        doc = frappe.get_doc("Baton Workflow", name)
        doc.check_permission("write")
        doc.workflow_name = data.get("workflow_name") or doc.workflow_name
    else:
        doc = frappe.new_doc("Baton Workflow")
        # The document name is the workflow name, so two workflows cannot share
        # one. Rather than failing a plain "Create" click with a duplicate-key
        # error, suffix it -- the user renames it in the builder anyway.
        doc.workflow_name = _unique_name(data.get("workflow_name") or "Untitled workflow")
    doc.enabled = 1 if data.get("enabled") else 0
    doc.kind = data.get("kind") or "Workflow"
    if "description" in data:
        doc.description = data.get("description")
    doc.trigger_type = data.get("trigger_type") or "Manual"
    doc.trigger_doctype = data.get("trigger_doctype")
    doc.trigger_event = data.get("trigger_event")
    doc.cron = data.get("cron")
    doc.condition = data.get("condition")
    doc.trigger_event_name = data.get("trigger_event_name")

    # The nodes table is cleared and rebuilt, so anything not copied across here
    # really is destroyed on every save -- unlike the parent fields above, which
    # survive simply by not being touched. Retry and error policy are editable
    # from Desk and invisible on the canvas, so they need carrying across
    # explicitly.
    _save_triggers(doc, data.get("triggers"))

    previous = {n.node_id: n for n in doc.nodes}

    doc.set("nodes", [])
    for n in data.get("nodes") or []:
        was = previous.get(n.get("node_id"))

        def kept(key, default):
            """Take the posted value, else what was already stored, else default."""
            if key in n and n.get(key) is not None:
                return n.get(key)
            return getattr(was, key, default) if was else default

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
                "save_as": n.get("save_as"),
                "max_retries": kept("max_retries", 0),
                "retry_delay": kept("retry_delay", 30),
                "on_error": kept("on_error", "Fail run"),
                # Cleared explicitly rather than kept, so removing a fallback in
                # the builder actually removes it.
                "fallback_node": (n.get("fallback_node")
                                  if "fallback_node" in n
                                  else kept("fallback_node", None)),
            },
        )

    doc.save()
    frappe.db.commit()
    return get_workflow(doc.name)


@frappe.whitelist()
def rename_workflow(name, new_name):
    """Rename a workflow.

    workflow_name is the document name, so this is a real rename -- every
    Baton Workflow Run linked to it has to be repointed, which frappe.rename_doc
    does for us. Doing it with a plain field write would orphan the run history.
    """
    frappe.only_for(["System Manager", "Sales Manager"])
    new_name = (new_name or "").strip()
    if not new_name:
        frappe.throw(_("A workflow needs a name."))
    if new_name == name:
        return name
    if frappe.db.exists("Baton Workflow", new_name):
        frappe.throw(_("A workflow called {0} already exists.").format(new_name))

    frappe.rename_doc("Baton Workflow", name, new_name, force=True)
    frappe.db.set_value("Baton Workflow", new_name, "workflow_name", new_name)
    frappe.db.commit()
    return new_name


@frappe.whitelist()
def delete_workflow(name):
    frappe.only_for(["System Manager", "Sales Manager"])
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
def test_run(name, reference_doctype=None, reference_name=None, credential=None):
    from baton.workflow.engine import run_workflow

    frappe.only_for(["System Manager", "Sales Manager"])

    doc = None
    subject_doctype = None

    if reference_doctype and reference_name:
        doc = frappe.get_doc(reference_doctype, reference_name)
    elif frappe.db.exists("Baton Workflow", name):
        # Test against the newest record of whatever the workflow triggers on, so
        # a manual test exercises the same shape a real trigger would.
        #
        # This reads the triggers child table. It used to read the parent's
        # scalar `trigger_doctype`, which the builder stopped writing when
        # triggers became a table -- so every test ran with no document and
        # every node that touches `doc` silently skipped, while the run still
        # reported Completed.
        subject_doctype = frappe.db.get_value(
            "Baton Workflow Trigger",
            {"parent": name, "parenttype": "Baton Workflow",
             "trigger_type": "Document Event"},
            "trigger_doctype",
        )
        if subject_doctype:
            latest = frappe.get_all(subject_doctype, limit=1,
                                    order_by="modified desc", pluck="name")
            if latest:
                doc = frappe.get_doc(subject_doctype, latest[0])

    # A test must run even when the workflow is switched off, and run_workflow
    # already allows that for run_reason="test" (engine.py). This used to flip
    # `enabled` to 1 and restore it in a finally -- which left the workflow
    # permanently live, messaging real customers, if the worker died between the
    # two commits.
    from baton.llm import use_client_credential

    with use_client_credential(credential):
        run_name = run_workflow(name, doc=doc, run_reason="test")

    if not run_name:
        return {"ok": False, "message": _("Workflow condition did not match; nothing ran.")}

    run = get_run(run_name)

    # A test that ran against nothing is not a passing test. Say so, rather than
    # showing a green Completed for a run where every node skipped.
    warning = None
    if not doc:
        if subject_doctype:
            warning = _("No {0} exists yet, so this ran without a record. "
                        "Steps that need one were skipped.").format(_(subject_doctype))
        elif any(s["status"] == "Skipped" for s in run["steps"]):
            warning = _("This ran without a record, so some steps were skipped. "
                        "Add a trigger, or test from a specific record.")

    return {"ok": True, "run": run, "warning": warning}


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
    """Everything needed to answer "what happened, and why".

    The steps say what each node did; the action log says why it decided to --
    including the refusals, which are the interesting half. A message that was
    never sent leaves a Skipped log row with a reason and no step output at all,
    so showing steps alone would make a suppressed send look like nothing
    happening.
    """
    doc = frappe.get_doc("Baton Workflow Run", name)

    log = frappe.get_all(
        "Baton Action Log",
        filters={"workflow_run": doc.name},
        fields=["action", "status", "node_id", "decision", "reason", "error",
                "latency_ms", "creation"],
        order_by="creation asc",
    ) if frappe.db.table_exists("Baton Action Log") else []

    return {
        "name": doc.name,
        "workflow": doc.workflow,
        "status": doc.status,
        "error": doc.error,
        "reference_doctype": doc.reference_doctype,
        "reference_name": doc.reference_name,
        "creation": doc.creation,
        "run_reason": doc.get("run_reason"),
        "waiting_for": doc.get("waiting_for"),
        "resume_at": doc.get("resume_at"),
        "resume_node": doc.get("resume_node"),
        "cancelled_reason": doc.get("cancelled_reason"),
        "log": log,
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
