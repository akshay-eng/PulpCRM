"""Conversational agent definitions.

An Agent is a *definition*, not a runtime -- exactly the relationship
`Baton Qualification Profile` already has with agents/qualification.py. The
`AI Conversation` node executes one.

The two child tables are the anti-drift devices. `Baton Agent Option` is the
closed set the model may classify into, so it cannot invent a service that is
not sold. `Baton Agent Outcome` maps a fact key to a real CRM field, so the
model never names a fieldname -- an admin does, once, here.
"""

import frappe

from baton.setup_phase1 import _add_fields, _doctype, _extend_select


def install():
    _doctype(
        "Baton Agent Option",
        [
            {"fieldname": "key", "fieldtype": "Data", "label": "Key", "reqd": 1,
             "in_list_view": 1, "description": "What the model returns, e.g. web_design"},
            {"fieldname": "label", "fieldtype": "Data", "label": "Label", "reqd": 1,
             "in_list_view": 1},
            {"fieldname": "col_o", "fieldtype": "Column Break"},
            {"fieldname": "description", "fieldtype": "Small Text", "label": "When to pick this"},
            {"fieldname": "synonyms", "fieldtype": "Data", "label": "Also called",
             "description": "Comma separated, to help the model recognise it."},
        ],
        istable=1,
    )

    _doctype(
        "Baton Agent Outcome",
        [
            {"fieldname": "key", "fieldtype": "Data", "label": "Fact", "reqd": 1,
             "in_list_view": 1, "description": "What the model may report, e.g. budget"},
            {"fieldname": "label", "fieldtype": "Data", "label": "Label", "in_list_view": 1},
            {"fieldname": "required", "fieldtype": "Check", "label": "Required", "default": "0",
             "in_list_view": 1,
             "description": "The agent cannot finish until this has been answered."},
            {"fieldname": "col_oc", "fieldtype": "Column Break"},
            {"fieldname": "target_doctype", "fieldtype": "Link", "label": "Write to record",
             "options": "DocType"},
            {"fieldname": "target_field", "fieldtype": "Data", "label": "Write to field",
             "description": "Blank keeps the fact on the run only."},
        ],
        istable=1,
    )

    _doctype(
        "Baton Agent",
        [
            {"fieldname": "agent_name", "fieldtype": "Data", "label": "Name", "reqd": 1,
             "unique": 1, "in_list_view": 1},
            {"fieldname": "enabled", "fieldtype": "Check", "label": "Enabled", "default": "1",
             "in_list_view": 1},
            {"fieldname": "col_a", "fieldtype": "Column Break"},
            {"fieldname": "purpose", "fieldtype": "Data", "label": "Model purpose",
             "default": "Conversation",
             "description": "Which Baton AI Model to use. Falls back to the default model."},
            {"fieldname": "channel", "fieldtype": "Select", "label": "Channel",
             "options": "WhatsApp\nEmail\nAny", "default": "WhatsApp"},

            {"fieldname": "sec_brief", "fieldtype": "Section Break", "label": "Brief"},
            {"fieldname": "goal", "fieldtype": "Small Text", "label": "Goal", "reqd": 1,
             "description": "One sentence. What is this conversation for?"},
            {"fieldname": "persona", "fieldtype": "Small Text", "label": "Tone",
             "description": "How it should sound. The agent signature is appended automatically."},
            {"fieldname": "business_context", "fieldtype": "Text", "label": "Business context",
             "description": "The only thing the agent may assume about what you sell."},
            {"fieldname": "guardrails", "fieldtype": "Text", "label": "Guardrails",
             "default": "Never quote prices or discounts.\n"
                        "Never promise a delivery date.\n"
                        "Never claim to be a human.\n"
                        "If you are unsure, hand over to a colleague."},

            {"fieldname": "sec_opts", "fieldtype": "Section Break", "label": "What it is choosing between"},
            {"fieldname": "options", "fieldtype": "Table", "label": "Options",
             "options": "Baton Agent Option"},
            {"fieldname": "sec_out", "fieldtype": "Section Break", "label": "What it should find out"},
            {"fieldname": "outcomes", "fieldtype": "Table", "label": "Outcomes",
             "options": "Baton Agent Outcome"},

            {"fieldname": "sec_lim", "fieldtype": "Section Break", "label": "Limits"},
            {"fieldname": "max_turns", "fieldtype": "Int", "label": "Max turns", "default": "6",
             "description": "An agent that talks to a customer twelve times unsupervised "
                            "is a support ticket."},
            {"fieldname": "max_reprompts", "fieldtype": "Int", "label": "Max re-prompts",
             "default": "1"},
            {"fieldname": "col_l", "fieldtype": "Column Break"},
            {"fieldname": "reply_timeout_hours", "fieldtype": "Int", "label": "Give up after (hours)",
             "default": "24"},
            {"fieldname": "transcript_limit", "fieldtype": "Int", "label": "Transcript messages",
             "default": "30"},
        ],
        autoname="field:agent_name",
        title_field="agent_name",
    )

    _extend_select("Baton Workflow Node", "node_type", ["AI Conversation"])

    frappe.db.commit()
    print("Agent doctypes ready.")


def seed_default():
    """A worked example, switched off, so the shape is obvious before you build one."""
    if frappe.db.exists("Baton Agent", "Service Qualifier"):
        print("  = Service Qualifier exists")
        return

    doc = frappe.get_doc({
        "doctype": "Baton Agent",
        "agent_name": "Service Qualifier",
        "enabled": 0,
        "channel": "WhatsApp",
        "goal": "Find out which service the customer needs, then hand over to book a call.",
        "persona": "Warm, brief, and plain-spoken. Two sentences at most per message.",
        "business_context": "We build websites, mobile apps, and run paid advertising.",
        "options": [
            {"key": "web", "label": "Website", "description": "Marketing sites, ecommerce, redesigns.",
             "synonyms": "site, webpage, landing page"},
            {"key": "app", "label": "Mobile app", "description": "iOS or Android applications.",
             "synonyms": "ios, android, mobile"},
            {"key": "ads", "label": "Paid advertising", "description": "Google or Meta ad campaigns.",
             "synonyms": "google ads, facebook ads, ppc"},
        ],
        "outcomes": [
            {"key": "service", "label": "Service wanted", "required": 1},
            {"key": "timeline", "label": "When they need it", "required": 0},
            {"key": "budget", "label": "Budget mentioned", "required": 0},
        ],
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    print("  + Service Qualifier (disabled)")


def install_all():
    install()
    seed_default()
