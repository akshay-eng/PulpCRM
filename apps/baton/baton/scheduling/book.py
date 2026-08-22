"""Holding a slot, then turning the hold into a real calendar entry.

Two decisions worth knowing.

**Offer without holding; hold at acceptance.** Reserving all three offered slots
would let one lead who never replies block a rep's calendar for a day. The race
between offering and accepting is real but narrow, and it is handled by the
unique `hold_key` -- whoever inserts first wins, and the loser re-offers.

**Google sync happens after the confirmation, not before it.** frappe's
`insert_event_in_google_calendar` throws on an API error and runs as an
after_insert hook, so a Google outage would roll back a booking we had already
promised the customer. The Event is written with sync off, the customer is told,
and the sync is enqueued afterwards where a retry costs nothing.
"""

import frappe
from frappe.utils import add_to_date, now_datetime

from baton.audit import log_action

HOLD_MINUTES = 15


def hold_key(user, slot_start):
    return f"{user or 'any'}|{frappe.utils.get_datetime(slot_start):%Y%m%d%H%M}"


def hold(user, slot_start, slot_end, reference_doctype=None, reference_name=None,
         service=None, workflow_run=None):
    """Claim a slot. Returns (hold_doc, None) or (None, reason)."""
    try:
        doc = frappe.get_doc({
            "doctype": "Baton Booking Hold",
            "hold_key": hold_key(user, slot_start),
            "status": "Held",
            "user": user,
            "slot_start": slot_start,
            "slot_end": slot_end,
            "expires_at": add_to_date(now_datetime(), minutes=HOLD_MINUTES),
            "reference_doctype": reference_doctype,
            "reference_name": reference_name,
            "service": service,
            "workflow_run": workflow_run,
        }).insert(ignore_permissions=True)
        frappe.db.commit()
        return doc, None
    except frappe.UniqueValidationError:
        # Someone else took it between the offer and the reply. This except
        # clause is the entire concurrency control.
        frappe.db.rollback()
        return None, "that time was taken a moment ago"


def release(hold_name, reason="released"):
    """Give a slot back. hold_key goes NULL so the unique index frees it."""
    frappe.db.set_value("Baton Booking Hold", hold_name, {
        "status": "Released",
        "hold_key": None,
    })
    frappe.db.commit()


def confirm(hold_doc, subject, description=None, attendee_contact=None,
            google_calendar=None, add_video=False):
    """Turn a held slot into an Event. Returns the Event name."""
    event = frappe.get_doc({
        "doctype": "Event",
        "subject": subject,
        "starts_on": hold_doc.slot_start,
        "ends_on": hold_doc.slot_end,
        "event_category": "Meeting",
        "event_type": "Private",
        "status": "Open",
        "description": description,
        "reference_doctype": hold_doc.reference_doctype,
        "reference_docname": hold_doc.reference_name,
        # Sync is switched on afterwards, out of band -- see the module docstring.
        "sync_with_google_calendar": 0,
    })

    if hold_doc.user:
        event.append("event_participants", {
            "reference_doctype": "User", "reference_docname": hold_doc.user,
        })
    if attendee_contact and frappe.db.exists("Contact", attendee_contact):
        event.append("event_participants", {
            "reference_doctype": "Contact", "reference_docname": attendee_contact,
        })

    event.insert(ignore_permissions=True)

    # get_events filters on `owner`, so an Event owned by Administrator is
    # invisible when we next ask what the rep is busy with -- and the very next
    # slot computation would offer this slot again.
    if hold_doc.user:
        event.db_set("owner", hold_doc.user, update_modified=False)

    frappe.db.set_value("Baton Booking Hold", hold_doc.name, {
        "status": "Confirmed", "event": event.name,
    })
    frappe.db.commit()

    if google_calendar:
        frappe.enqueue(
            "baton.scheduling.book.push_to_google",
            queue="short",
            enqueue_after_commit=True,
            event=event.name,
            google_calendar=google_calendar,
            add_video=1 if add_video else 0,
        )

    log_action("booking.confirm",
               reference_doctype=hold_doc.reference_doctype,
               reference_name=hold_doc.reference_name,
               workflow_run=hold_doc.workflow_run,
               external_id=event.name,
               output={"starts_on": str(hold_doc.slot_start), "with": hold_doc.user})
    return event.name


def push_to_google(event, google_calendar, add_video=0):
    """Flip sync on so frappe's own integration pushes it.

    Failures are logged, never raised at the customer: by the time this runs
    they already have their confirmation, and RQ will retry.
    """
    try:
        doc = frappe.get_doc("Event", event)
        doc.sync_with_google_calendar = 1
        doc.google_calendar = google_calendar
        if add_video:
            doc.add_video_conferencing = 1
        doc.save(ignore_permissions=True)
        frappe.db.commit()
    except Exception as e:
        log_action("booking.google_sync", status="Failed",
                   external_id=event, error=str(e)[:500],
                   reason="Booking stands; only the calendar copy failed.")
        frappe.log_error(title=f"Baton: Google sync failed for {event}")


def release_expired_holds(limit=200):
    """Scheduler job: hand back slots nobody confirmed."""
    if not frappe.db.table_exists("Baton Booking Hold"):
        return

    stale = frappe.get_all(
        "Baton Booking Hold",
        filters={"status": "Held", "expires_at": ["<", now_datetime()]},
        pluck="name", limit_page_length=limit,
    )
    for name in stale:
        release(name, reason="hold expired")
    return len(stale)
