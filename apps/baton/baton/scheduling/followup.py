"""Waking up once a booked meeting has ended, to ask how it went.

Deliberately not a bot connector that lets a bot "find its own due
meetings" -- no connector exposes the Event doctype today, and building one
just so a bot can discover which records need talking to would duplicate
what a three-line query already does, for no benefit. This module's whole
job is discovery; talking to the lead is the Meeting Follow-up bot's job,
same as any other bot run against a specific record.

Also deliberately not built on Baton Followup Policy -- that machinery
generates a pre-response nurture ladder from a lead's creation, switched off
by default. This wakes once, per meeting, well after creation, which needs
a different trigger entirely (an Event's end time), not a bigger ladder.
"""

import frappe
from frappe.utils import now_datetime

from baton.audit import already_done, log_action

BOT_NAME = "Meeting Follow-up"
RUN_QUEUE = "long"
RUN_TIMEOUT = 1500


def tick(limit=50):
    """Scheduler entry point: find meetings that ended and haven't been
    followed up, and start the follow-up bot against each one.

    Marked done at *enqueue* time, not completion -- a slow or failed run
    must not cause the same meeting to be re-queued on every subsequent
    tick, the same idempotency shape the workflow engine's own action keys
    already use.
    """
    if not frappe.db.exists("Baton Bot", BOT_NAME):
        return
    if not frappe.db.get_value("Baton Bot", BOT_NAME, "enabled"):
        return

    due = frappe.get_all(
        "Event",
        filters={
            "event_category": "Meeting",
            "ends_on": ["<", now_datetime()],
            "reference_doctype": ["in", ["CRM Lead", "CRM Deal"]],
            "reference_docname": ["is", "set"],
        },
        fields=["name", "reference_doctype", "reference_docname", "ends_on"],
        order_by="ends_on asc",
        limit_page_length=limit,
    )

    for ev in due:
        key = f"meeting_followup:{ev.name}"
        if already_done(key):
            continue

        frappe.enqueue(
            "baton.bots.runtime.run_bot",
            queue=RUN_QUEUE, timeout=RUN_TIMEOUT,
            enqueue_after_commit=True,
            bot_name=BOT_NAME,
            reference_doctype=ev.reference_doctype,
            reference_name=ev.reference_docname,
            run_reason="schedule",
        )
        log_action("meeting.followup.queued", actor_type="SYSTEM",
                  reference_doctype=ev.reference_doctype,
                  reference_name=ev.reference_docname,
                  idempotency_key=key, external_id=ev.name,
                  reason=f"Meeting ended {ev.ends_on}; asking how it went.")

    frappe.db.commit()
