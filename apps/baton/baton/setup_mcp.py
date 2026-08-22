"""MCP server registry — how a bot borrows tools from another program.

    bench --site crm.localhost execute baton.setup_mcp.install
"""

import frappe

from baton.setup_phase1 import _doctype


def install():
    _doctype(
        "Baton MCP Tool",
        [
            {"fieldname": "tool_name", "fieldtype": "Data", "label": "Tool", "reqd": 1,
             "in_list_view": 1, "read_only": 1},
            {"fieldname": "enabled", "fieldtype": "Check", "label": "Allowed", "default": "0",
             "in_list_view": 1,
             "description": "Discovery does not grant use. A tool a bot may call is one "
                            "someone ticked."},
            {"fieldname": "col_t", "fieldtype": "Column Break"},
            {"fieldname": "description", "fieldtype": "Small Text", "label": "What it does",
             "read_only": 1, "in_list_view": 1},
            {"fieldname": "input_schema", "fieldtype": "Code", "label": "Arguments",
             "options": "JSON", "read_only": 1},
        ],
        istable=1,
    )

    _doctype(
        "Baton MCP Server",
        [
            {"fieldname": "server_name", "fieldtype": "Data", "label": "Name", "reqd": 1,
             "unique": 1, "in_list_view": 1},
            {"fieldname": "enabled", "fieldtype": "Check", "label": "Enabled", "default": "0",
             "in_list_view": 1},
            {"fieldname": "col_s", "fieldtype": "Column Break"},
            {"fieldname": "transport", "fieldtype": "Select", "label": "Transport",
             "options": "Streamable HTTP\nStdio", "default": "Streamable HTTP",
             "reqd": 1, "in_list_view": 1},
            {"fieldname": "description", "fieldtype": "Small Text", "label": "Description"},

            {"fieldname": "sec_http", "fieldtype": "Section Break", "label": "Connection",
             "depends_on": "eval:doc.transport=='Streamable HTTP'"},
            {"fieldname": "url", "fieldtype": "Data", "label": "URL",
             "description": "e.g. https://tools.example.com/mcp"},
            {"fieldname": "col_h", "fieldtype": "Column Break"},
            {"fieldname": "auth_header", "fieldtype": "Data", "label": "Auth header name",
             "description": "e.g. Authorization. Leave blank if the server needs none."},
            {"fieldname": "auth_value", "fieldtype": "Password", "label": "Auth header value",
             "description": "e.g. Bearer xxx. Stored encrypted, never sent to the browser."},

            {"fieldname": "sec_stdio", "fieldtype": "Section Break", "label": "Command",
             "depends_on": "eval:doc.transport=='Stdio'"},
            {"fieldname": "command", "fieldtype": "Data", "label": "Command",
             "description": "e.g. npx"},
            {"fieldname": "args", "fieldtype": "Small Text", "label": "Arguments",
             "description": "One per line, e.g. -y then @modelcontextprotocol/server-filesystem"},
            {"fieldname": "col_st", "fieldtype": "Column Break"},
            {"fieldname": "cwd", "fieldtype": "Data", "label": "Working directory"},
            {"fieldname": "env_json", "fieldtype": "Code", "label": "Environment (JSON)",
             "options": "JSON",
             "description": "Values here are passed to the process. Prefer a secret in "
                            "auth_value where the server supports a header."},

            {"fieldname": "sec_tools", "fieldtype": "Section Break", "label": "Tools"},
            {"fieldname": "tools", "fieldtype": "Table", "label": "Discovered tools",
             "options": "Baton MCP Tool"},
            {"fieldname": "last_discovered_at", "fieldtype": "Datetime",
             "label": "Last discovered", "read_only": 1},
            {"fieldname": "last_error", "fieldtype": "Small Text", "label": "Last error",
             "read_only": 1},
            {"fieldname": "timeout", "fieldtype": "Int", "label": "Timeout (s)", "default": "60"},
        ],
        title_field="server_name",
        autoname="field:server_name",
    )

    frappe.db.commit()
    print("MCP doctypes ready.")
