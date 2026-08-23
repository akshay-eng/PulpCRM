"""Send queued mail immediately instead of waiting for the scheduler.

Frappe queues outbound mail and lets `frappe.email.queue.flush` deliver it on
the scheduler's tick -- 240 seconds by default. That is fine for notifications
and wrong for a CRM: someone presses Send on a deal, watches nothing happen for
up to four minutes, and reasonably concludes email is broken.

This hands each new queue row straight to a background worker. The scheduler
still runs and still catches anything this misses (a worker restart mid-send, a
transient SMTP failure), so the change is a latency fix rather than a
replacement for the queue.

Double sending is prevented the same way flush prevents it: the row is loaded
`for_update`, and `EmailQueue.can_send_now()` refuses anything whose status has
already moved off "Not Sent". Whichever of the two gets the lock first wins and
the other declines.
"""

import frappe
from frappe.utils import cint, get_datetime, now_datetime


def send_now(doc, method=None):
    """Queue an immediate delivery attempt for a freshly created Email Queue row."""
    if getattr(frappe.flags, "in_install", False) or getattr(frappe.flags, "in_migrate", False):
        return
    if getattr(frappe.flags, "in_test", False):
        return

    # A scheduled send is scheduled on purpose.
    if doc.send_after and get_datetime(doc.send_after) > now_datetime():
        return
    if doc.status not in ("Not Sent", "Partially Sent"):
        return
    if frappe.are_emails_muted():
        return
    if cint(frappe.db.get_default("suspend_email_queue")) == 1:
        return

    frappe.enqueue(
        "baton.api.email.deliver",
        queue="short",
        # After commit, or the worker can look for a row this transaction has
        # not written yet and find nothing.
        enqueue_after_commit=True,
        job_id=f"baton-email-{doc.name}",
        deduplicate=True,
        queue_name=doc.name,
    )


def deliver(queue_name):
    """Deliver one queued email, or leave it for the scheduler."""
    if not frappe.db.exists("Email Queue", queue_name):
        return

    from baton.audit import log_action

    try:
        # for_update takes the same row lock flush() takes, so the scheduler and
        # this worker cannot both send the same message.
        row = frappe.get_doc("Email Queue", queue_name, for_update=True)
        if row.status not in ("Not Sent", "Partially Sent"):
            return
        row.send()
        frappe.db.commit()
    except Exception as e:
        # Left in the queue deliberately: the scheduler retries it, so a
        # transient SMTP failure delays an email rather than losing it.
        frappe.db.rollback()
        log_action("email.immediate_send_failed", status="Failed", actor_type="SYSTEM",
                   error=str(e)[:500], output={"queue": queue_name},
                   reason="Left queued for the scheduler to retry")
