"""Carry bots across the connector split.

Two things changed shape under existing bots:

  * `crm_operations` bundled six unrelated verbs behind one checkbox. It is now
    five connectors, so a bot can be granted "comment on records" without also
    being granted "reassign them".
  * The email connector's fixed address lived in a bare `to` key. Whether a bot
    emails the record's contact or a fixed address is now an explicit choice,
    because inferring it from a blank box made "report to me" and "talk to the
    customer" the same setting.

Both are rewritten in place. A bot that was working keeps working, with the
same tools and the same recipient, and its canvas now shows what it can
actually do.
"""

import json

import frappe

# One old connector becomes several. A bot that had the bundle keeps every verb
# it had -- the split is about what can be granted next time, not about quietly
# taking capabilities away from bots that are already running.
SPLIT = ["crm_assignment", "crm_comments", "crm_call_logging",
         "crm_field_options", "crm_search"]

LABELS = {
    "crm_assignment": "Assignment",
    "crm_comments": "Comments",
    "crm_call_logging": "Call logging",
    "crm_field_options": "Field options",
    "crm_search": "Search",
}


def execute():
    if not frappe.db.table_exists("Baton Bot"):
        return

    _split_operations()
    _make_recipients_explicit()


def _split_operations():
    rows = frappe.get_all(
        "Baton Bot Connector",
        filters={"connector": "crm_operations"},
        fields=["name", "parent", "enabled", "position_x", "position_y", "idx"],
    )
    for row in rows:
        bot = frappe.get_doc("Baton Bot", row.parent)
        have = {c.connector for c in bot.connectors}
        # Fan out below the tile being replaced so the canvas stays readable
        # rather than stacking five nodes on one point.
        for i, cid in enumerate(SPLIT):
            if cid in have:
                continue
            bot.append("connectors", {
                "connector": cid,
                "label": LABELS[cid],
                "enabled": row.enabled,
                "config": "{}",
                "position_x": (row.position_x or 0) + (i % 2) * 260,
                "position_y": (row.position_y or 0) + (i // 2) * 120,
            })
        bot.connectors = [c for c in bot.connectors if c.connector != "crm_operations"]
        for i, c in enumerate(bot.connectors, start=1):
            c.idx = i
        bot.save(ignore_permissions=True)

    if rows:
        frappe.db.commit()


def _make_recipients_explicit():
    for row in frappe.get_all("Baton Bot Connector",
                              filters={"connector": ["in", ("email", "whatsapp")]},
                              fields=["name", "config"]):
        try:
            cfg = json.loads(row.config) if row.config else {}
        except (ValueError, TypeError):
            continue
        if not isinstance(cfg, dict) or "recipient_mode" in cfg:
            continue

        fixed = (cfg.pop("to", "") or "").strip()
        cfg["recipient_mode"] = "fixed" if fixed else "record"
        if fixed:
            cfg["recipient"] = fixed
        frappe.db.set_value("Baton Bot Connector", row.name, "config",
                            json.dumps(cfg), update_modified=False)
    frappe.db.commit()
