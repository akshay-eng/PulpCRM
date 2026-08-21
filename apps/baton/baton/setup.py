"""Creates Baton's DocTypes.

Run once with:
    bench --site crm.localhost execute baton.setup.install

Written as code rather than hand-authored JSON because Frappe writes the
canonical .json/.py files into the module folder itself when developer_mode is
on -- generating them by hand invites schema drift.
"""

import frappe

MODULE = "Baton"


def _perms(roles=("System Manager", "Sales User")):
    return [
        {
            "role": r,
            "read": 1,
            "write": 1,
            "create": 1,
            "delete": 1 if r == "System Manager" else 0,
            "report": 1,
            "share": 1,
        }
        for r in roles
    ]


def _doctype(name, fields, **kwargs):
    if frappe.db.exists("DocType", name):
        print(f"  = {name} (exists)")
        return
    doc = frappe.get_doc(
        {
            "doctype": "DocType",
            "name": name,
            "module": MODULE,
            "custom": 0,
            "fields": fields,
            "permissions": [] if kwargs.get("istable") else _perms(),
            **kwargs,
        }
    )
    doc.insert(ignore_permissions=True)
    print(f"  + {name}")


def install():
    frappe.flags.in_install = True

    # ---------------------------------------------------------------- settings
    _doctype(
        "Baton Settings",
        [
            {"fieldname": "ai_section", "fieldtype": "Section Break", "label": "AI Provider"},
            {"fieldname": "ai_enabled", "fieldtype": "Check", "label": "Enable AI", "default": "0"},
            {
                "fieldname": "ai_base_url",
                "fieldtype": "Data",
                "label": "OpenAI-compatible Base URL",
                "description": "e.g. https://api.groq.com/openai/v1 or https://generativelanguage.googleapis.com/v1beta/openai",
                "default": "https://api.groq.com/openai/v1",
            },
            {"fieldname": "ai_model", "fieldtype": "Data", "label": "Model", "default": "llama-3.3-70b-versatile"},
            {"fieldname": "col_ai", "fieldtype": "Column Break"},
            {"fieldname": "ai_api_key", "fieldtype": "Password", "label": "API Key"},
            {
                "fieldname": "ai_max_rows",
                "fieldtype": "Int",
                "label": "Max rows returned to the model",
                "default": "50",
                "description": "Caps how much data a single chat answer can pull.",
            },
            {"fieldname": "wa_section", "fieldtype": "Section Break", "label": "WhatsApp"},
            {
                "fieldname": "agent_signature",
                "fieldtype": "Data",
                "label": "Agent signature",
                "description": "Appended to AI-authored WhatsApp messages so recipients are not misled about who is writing.",
            },
            {
                "fieldname": "ai_turn_cap",
                "fieldtype": "Int",
                "label": "AI turns before human handover",
                "default": "6",
            },
        ],
        issingle=1,
    )

    # ---------------------------------------------------------------- approval
    _doctype(
        "Baton Approval",
        [
            {"fieldname": "code", "fieldtype": "Data", "label": "Code", "read_only": 1,
             "description": "Short handle the founder replies with, e.g. A7."},
            {"fieldname": "kind", "fieldtype": "Select", "label": "Kind", "reqd": 1,
             "options": "Send Message\nSend Quote\nSend Invoice\nEscalate\nOther"},
            {"fieldname": "status", "fieldtype": "Select", "label": "Status", "default": "Pending",
             "options": "Pending\nApproved\nRejected\nExpired", "in_list_view": 1, "in_standard_filter": 1},
            {"fieldname": "col_a", "fieldtype": "Column Break"},
            {"fieldname": "reference_doctype", "fieldtype": "Link", "label": "Reference Type", "options": "DocType"},
            {"fieldname": "reference_name", "fieldtype": "Dynamic Link", "label": "Reference", "options": "reference_doctype"},
            {"fieldname": "expires_at", "fieldtype": "Datetime", "label": "Expires At"},
            {"fieldname": "sec_body", "fieldtype": "Section Break"},
            {"fieldname": "draft_text", "fieldtype": "Small Text", "label": "Draft",
             "description": "What will be sent verbatim if approved."},
            {"fieldname": "payload", "fieldtype": "Code", "label": "Payload (JSON)", "options": "JSON"},
            {"fieldname": "sec_res", "fieldtype": "Section Break", "label": "Resolution"},
            {"fieldname": "resolved_by", "fieldtype": "Link", "label": "Resolved By", "options": "User", "read_only": 1},
            {"fieldname": "resolved_at", "fieldtype": "Datetime", "label": "Resolved At", "read_only": 1},
            {"fieldname": "col_r", "fieldtype": "Column Break"},
            {"fieldname": "costs_template", "fieldtype": "Check", "label": "Costs a paid template",
             "description": "True when the 24h service window has closed, so sending bills as a template."},
        ],
        title_field="code",
        autoname="format:A{#####}",
    )

    # ------------------------------------------------------- workflow builder
    _doctype(
        "Baton Workflow Node",
        [
            {"fieldname": "node_id", "fieldtype": "Data", "label": "Node ID", "reqd": 1, "in_list_view": 1},
            {"fieldname": "node_type", "fieldtype": "Select", "label": "Type", "reqd": 1, "in_list_view": 1,
             "options": "Trigger\nCondition\nUpdate Field\nCreate Document\nSend WhatsApp\nSend Email\nAI Agent\nWait\nRequest Approval\nWebhook"},
            {"fieldname": "label", "fieldtype": "Data", "label": "Label", "in_list_view": 1},
            {"fieldname": "col_n", "fieldtype": "Column Break"},
            {"fieldname": "next_node", "fieldtype": "Data", "label": "Next Node"},
            {"fieldname": "next_node_alt", "fieldtype": "Data", "label": "Else Node",
             "description": "Taken when a Condition node evaluates false."},
            {"fieldname": "sec_cfg", "fieldtype": "Section Break"},
            {"fieldname": "config", "fieldtype": "Code", "label": "Config (JSON)", "options": "JSON"},
            {"fieldname": "position_x", "fieldtype": "Int", "label": "X", "hidden": 1},
            {"fieldname": "position_y", "fieldtype": "Int", "label": "Y", "hidden": 1},
        ],
        istable=1,
    )

    _doctype(
        "Baton Workflow",
        [
            {"fieldname": "workflow_name", "fieldtype": "Data", "label": "Name", "reqd": 1, "unique": 1, "in_list_view": 1},
            {"fieldname": "enabled", "fieldtype": "Check", "label": "Enabled", "default": "0", "in_list_view": 1},
            {"fieldname": "col_w", "fieldtype": "Column Break"},
            {"fieldname": "trigger_type", "fieldtype": "Select", "label": "Trigger", "reqd": 1, "in_list_view": 1,
             "options": "Document Event\nScheduled\nManual\nWebhook"},
            {"fieldname": "trigger_doctype", "fieldtype": "Link", "label": "Trigger DocType", "options": "DocType",
             "depends_on": "eval:doc.trigger_type=='Document Event'"},
            {"fieldname": "trigger_event", "fieldtype": "Select", "label": "Event",
             "options": "after_insert\non_update\non_submit\non_cancel\non_trash",
             "depends_on": "eval:doc.trigger_type=='Document Event'"},
            {"fieldname": "cron", "fieldtype": "Data", "label": "Cron",
             "depends_on": "eval:doc.trigger_type=='Scheduled'",
             "description": "Standard 5-field cron, e.g. 0 9 * * * for 9am daily."},
            {"fieldname": "sec_cond", "fieldtype": "Section Break"},
            {"fieldname": "condition", "fieldtype": "Code", "label": "Condition",
             "description": "Optional Python expression over `doc`. Blank means always run."},
            {"fieldname": "sec_nodes", "fieldtype": "Section Break", "label": "Graph"},
            {"fieldname": "nodes", "fieldtype": "Table", "label": "Nodes", "options": "Baton Workflow Node"},
            {"fieldname": "graph", "fieldtype": "Code", "label": "Canvas layout (JSON)", "options": "JSON", "hidden": 1},
        ],
        title_field="workflow_name",
        autoname="field:workflow_name",
    )

    _doctype(
        "Baton Workflow Run Step",
        [
            {"fieldname": "node_id", "fieldtype": "Data", "label": "Node", "in_list_view": 1},
            {"fieldname": "node_type", "fieldtype": "Data", "label": "Type", "in_list_view": 1},
            {"fieldname": "status", "fieldtype": "Select", "label": "Status", "in_list_view": 1,
             "options": "Success\nFailed\nSkipped"},
            {"fieldname": "col_s", "fieldtype": "Column Break"},
            {"fieldname": "duration_ms", "fieldtype": "Int", "label": "ms"},
            {"fieldname": "sec_io", "fieldtype": "Section Break"},
            {"fieldname": "output", "fieldtype": "Code", "label": "Output", "options": "JSON"},
        ],
        istable=1,
    )

    _doctype(
        "Baton Workflow Run",
        [
            {"fieldname": "workflow", "fieldtype": "Link", "label": "Workflow", "options": "Baton Workflow",
             "reqd": 1, "in_list_view": 1},
            {"fieldname": "status", "fieldtype": "Select", "label": "Status", "default": "Running",
             "options": "Running\nCompleted\nFailed\nWaiting", "in_list_view": 1, "in_standard_filter": 1},
            {"fieldname": "col_r", "fieldtype": "Column Break"},
            {"fieldname": "reference_doctype", "fieldtype": "Link", "label": "Reference Type", "options": "DocType"},
            {"fieldname": "reference_name", "fieldtype": "Dynamic Link", "label": "Reference",
             "options": "reference_doctype", "in_list_view": 1},
            {"fieldname": "sec_steps", "fieldtype": "Section Break"},
            {"fieldname": "steps", "fieldtype": "Table", "label": "Steps", "options": "Baton Workflow Run Step"},
            {"fieldname": "error", "fieldtype": "Small Text", "label": "Error", "read_only": 1},
        ],
    )

    # ------------------------------------------------------------- ai chat
    _doctype(
        "Baton Chat Session",
        [
            {"fieldname": "title", "fieldtype": "Data", "label": "Title", "in_list_view": 1},
            {"fieldname": "user", "fieldtype": "Link", "label": "User", "options": "User", "in_list_view": 1},
        ],
        title_field="title",
    )

    _doctype(
        "Baton Chat Message",
        [
            {"fieldname": "session", "fieldtype": "Link", "label": "Session", "options": "Baton Chat Session",
             "reqd": 1, "in_list_view": 1},
            {"fieldname": "role", "fieldtype": "Select", "label": "Role", "options": "user\nassistant\nsystem",
             "in_list_view": 1},
            {"fieldname": "sec_c", "fieldtype": "Section Break"},
            {"fieldname": "content", "fieldtype": "Long Text", "label": "Content"},
            {"fieldname": "query_spec", "fieldtype": "Code", "label": "Query the model asked for", "options": "JSON",
             "description": "Kept so an answer can always be traced back to the query that produced it."},
            {"fieldname": "row_count", "fieldtype": "Int", "label": "Rows returned"},
        ],
    )

    frappe.db.commit()
    print("Baton doctypes ready.")


def install_custom_fields():
    """BATON's one-line differentiator, as a column on the shared message table.

    Human and AI replies live in ONE table distinguished by `baton_author`,
    rather than two systems reconciled afterwards. Everything downstream --
    "did a human already answer, so cancel the queued follow-up" -- is a filter
    on this column.
    """
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    if not frappe.db.exists("DocType", "WhatsApp Message"):
        print("  ! WhatsApp Message not found; skipping author field")
        return

    create_custom_fields(
        {
            "WhatsApp Message": [
                {
                    "fieldname": "baton_author",
                    "label": "Author",
                    "fieldtype": "Select",
                    "options": "contact\nhuman\nai",
                    "default": "contact",
                    "insert_after": "content_type",
                    "in_standard_filter": 1,
                    "description": "Who composed this message. 'ai' means Baton's agent wrote it.",
                },
                {
                    "fieldname": "baton_approval",
                    "label": "Approved via",
                    "fieldtype": "Link",
                    "options": "Baton Approval",
                    "insert_after": "baton_author",
                    "read_only": 1,
                },
            ]
        },
        ignore_validate=True,
    )
    frappe.db.commit()
    print("  + baton_author on WhatsApp Message")


def install_all():
    install()
    install_custom_fields()
