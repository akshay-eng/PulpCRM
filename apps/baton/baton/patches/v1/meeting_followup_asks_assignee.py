"""Redirect the existing "Meeting Follow-up" bot from the lead to the rep.

_install_bot() is idempotency-guarded (it skips outright if the bot already
exists), so re-running setup on an upgraded site would never touch an
already-installed bot's instructions or connectors. This patch is that
missing update, applied once, in place -- a site that customised the bot
further keeps whatever it changed beyond what's touched here.
"""

import frappe

BOT_NAME = "Meeting Follow-up"

INSTRUCTIONS = (
    "You were woken because a meeting with this lead or deal just ended. "
    "Use ask_assignee to ask whoever the record is assigned to, in one "
    "short message, how the call went -- not the lead, the rep who was "
    "actually on it. If nobody is assigned, raise a task and stop.\n\n"
    "When the assignee answers, write down what they told you with "
    "add_note, add_comment or create_task as fits, then act on it:\n"
    "  - Happy path: call convert_lead to turn the lead into a deal.\n"
    "  - Unhappy path: set the record's status to reflect that it did "
    "not pan out -- check list_options first for the exact values "
    "available (a Lead's Lost-type statuses, or a Deal's Lost status). "
    "A Lead also requires lost_reason whenever you set a Lost-type "
    "status -- pick the closest match (Pricing, Competition, Budget "
    "Constraints, etc.) from list_options, and only fall back to "
    "\"Other\" (with a short lost_notes explaining why) if nothing "
    "else fits.\n\n"
    "If they don't answer, that's fine; you'll simply have nothing to "
    "update. Never invent an outcome nobody told you."
)

GUARDRAILS = (
    "Never say the meeting happened a specific way unless the assignee "
    "told you so themselves.\n"
    "Never convert or mark a record lost on a guess -- only on what the "
    "assignee actually said.\n"
    "Keep the opening message under two sentences.\n"
    "If they ask something out of scope, say so plainly and return to "
    "asking how the meeting went."
)

ADD_CONNECTORS = ["crm_tasks", "crm_comments", "crm_field_options"]


def execute():
    if not frappe.db.exists("Baton Bot", BOT_NAME):
        return

    bot = frappe.get_doc("Baton Bot", BOT_NAME)
    bot.instructions = INSTRUCTIONS
    bot.guardrails = GUARDRAILS
    bot.connectors = [c for c in bot.connectors if c.connector != "email"]

    have = {c.connector for c in bot.connectors}
    for i, cid in enumerate(ADD_CONNECTORS):
        if cid in have:
            continue
        bot.append("connectors", {
            "connector": cid, "enabled": 1, "config": "{}",
            "position_x": 300 + (i % 2) * 260, "position_y": 500 + (i // 2) * 120,
        })

    bot.save(ignore_permissions=True)
    frappe.db.commit()
