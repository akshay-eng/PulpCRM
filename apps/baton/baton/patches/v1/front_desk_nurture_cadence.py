"""Turn on the deterministic no-reply cadence for the existing "Front desk"
bot, and tell it not to plan its own follow-up schedule any more.

Same reasoning as meeting_followup_asks_assignee.py: _install_bot() skips a
bot that already exists, so an upgrade alone never reaches an already
installed bot's instructions or settings.
"""

import frappe

BOT_NAME = "Front desk"

APPEND_TO_INSTRUCTIONS = (
    "\n\nIf they don't reply, you don't need to plan a follow-up schedule "
    "yourself -- you'll be told exactly when to send a nudge and on which "
    "channel, in order. Just write the wording for whichever attempt "
    "you're told you're on."
)


def execute():
    if not frappe.db.exists("Baton Bot", BOT_NAME):
        return

    bot = frappe.get_doc("Baton Bot", BOT_NAME)
    if APPEND_TO_INSTRUCTIONS.strip() not in (bot.instructions or ""):
        bot.instructions = (bot.instructions or "") + APPEND_TO_INSTRUCTIONS
    bot.nurture_cadence_enabled = 1
    bot.save(ignore_permissions=True)
    frappe.db.commit()
