"""Bots: the OpenClaw-shaped half of the product.

A Bot is deliberately *not* a workflow. A workflow is a graph you draw: this
step, then that step, branch here. A bot is a brain you brief -- instructions,
guardrails, a model -- with a set of connectors plugged into it. What it does in
what order is the model's business, inside the fence the connectors draw.

That difference is why this is a separate DocType rather than
`Baton Workflow.kind = "Bot"`, which is what it was before and which meant the
"bot" builder was just the workflow builder with two node types greyed out.

Runs are still `Baton Workflow Run` rows, because everything a run needs --
claim tokens, heartbeats, durable parks, step history, the inbound-reply
resume -- already exists there and a second copy would be a second place the
send gate can be bypassed.

    bench --site crm.localhost execute baton.setup_bots.install
"""

import frappe

from baton.setup_phase1 import _add_fields, _doctype, _extend_select


def install():
    # ------------------------------------------------------------ connectors
    # A connector is a capability the bot is granted, not a step it runs. Its
    # config is per-bot (which pipeline to write to, which mailbox to send
    # from); its *credential* is global and lives in Settings, which is why
    # there is no key field anywhere on this table.
    _doctype(
        "Baton Bot Connector",
        [
            {"fieldname": "connector", "fieldtype": "Data", "label": "Connector",
             "reqd": 1, "in_list_view": 1,
             "description": "Catalog id, e.g. crm_leads. See baton.bots.catalog."},
            {"fieldname": "label", "fieldtype": "Data", "label": "Label", "in_list_view": 1},
            {"fieldname": "enabled", "fieldtype": "Check", "label": "Enabled", "default": "1",
             "in_list_view": 1},
            {"fieldname": "col_bc", "fieldtype": "Column Break"},
            {"fieldname": "position_x", "fieldtype": "Int", "label": "X"},
            {"fieldname": "position_y", "fieldtype": "Int", "label": "Y"},
            {"fieldname": "sec_bc", "fieldtype": "Section Break"},
            {"fieldname": "config", "fieldtype": "Code", "label": "Config", "options": "JSON"},
        ],
        istable=1,
    )

    _doctype(
        "Baton Bot",
        [
            {"fieldname": "bot_name", "fieldtype": "Data", "label": "Name", "reqd": 1,
             "unique": 1, "in_list_view": 1},
            {"fieldname": "enabled", "fieldtype": "Check", "label": "Enabled", "default": "0",
             "in_list_view": 1,
             "description": "Off until someone turns it on. A bot acts on real customers."},
            {"fieldname": "col_b", "fieldtype": "Column Break"},
            {"fieldname": "description", "fieldtype": "Small Text", "label": "What it does"},
            {"fieldname": "sec_brief", "fieldtype": "Section Break", "label": "Brief"},
            {"fieldname": "instructions", "fieldtype": "Text", "label": "Instructions",
             "description": "What the bot is for and how it should behave."},
            {"fieldname": "guardrails", "fieldtype": "Text", "label": "Guardrails",
             "description": "What it must never do. Enforced in the prompt and, where "
                            "it can be, in code."},
            {"fieldname": "sec_model", "fieldtype": "Section Break", "label": "Model"},
            {"fieldname": "ai_model", "fieldtype": "Link", "label": "Model credential",
             "options": "Baton AI Model",
             "description": "Blank uses the default model for the Conversation purpose."},
            {"fieldname": "channel", "fieldtype": "Select", "label": "Talks on",
             "options": "WhatsApp\nEmail\nNone", "default": "WhatsApp"},
            {"fieldname": "col_m", "fieldtype": "Column Break"},
            {"fieldname": "max_steps", "fieldtype": "Int", "label": "Max steps per run",
             "default": "8",
             "description": "How many tool calls it may make before it has to stop."},
            {"fieldname": "reply_timeout_hours", "fieldtype": "Int",
             "label": "Give up waiting after (hours)", "default": "24"},
            {"fieldname": "sec_conn", "fieldtype": "Section Break", "label": "Connectors"},
            {"fieldname": "connectors", "fieldtype": "Table", "label": "Connectors",
             "options": "Baton Bot Connector"},
            {"fieldname": "sec_trig", "fieldtype": "Section Break", "label": "Triggers"},
            {"fieldname": "triggers", "fieldtype": "Table", "label": "Triggers",
             "options": "Baton Workflow Trigger"},
            {"fieldname": "sec_pos", "fieldtype": "Section Break", "label": "Canvas"},
            {"fieldname": "position_x", "fieldtype": "Int", "label": "X", "default": "420"},
            {"fieldname": "position_y", "fieldtype": "Int", "label": "Y", "default": "260"},
        ],
        title_field="bot_name",
        autoname="field:bot_name",
    )

    # A run belongs to a workflow *or* a bot, so `workflow` can no longer be
    # required. Everything that reads a run already tolerates a blank one.
    _make_optional("Baton Workflow Run", "workflow")
    _add_fields("Baton Workflow Run", [
        {"fieldname": "bot", "fieldtype": "Link", "label": "Bot", "options": "Baton Bot"},
    ])
    _add_fields("Baton Action Log", [
        {"fieldname": "bot", "fieldtype": "Link", "label": "Bot", "options": "Baton Bot"},
    ])

    # The trigger table is shared with workflows, and a bot may be woken by an
    # inbound message -- a workflow never is, because it starts from a record.
    _extend_select("Baton Workflow Trigger", "trigger_type", ["Inbound Message"])

    frappe.db.commit()
    print("Bots ready.")


def _make_optional(doctype, fieldname):
    dt = frappe.get_doc("DocType", doctype)
    for f in dt.fields:
        if f.fieldname == fieldname and f.reqd:
            f.reqd = 0
            dt.save(ignore_permissions=True)
            print(f"  + {doctype}.{fieldname} no longer required")
            return
    print(f"  = {doctype}.{fieldname} (already optional)")
