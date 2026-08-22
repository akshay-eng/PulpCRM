"""When someone is already booked.

Reads frappe's own `Event` rather than keeping a cache, and specifically through
`event.get_events` rather than a plain get_all: get_events **expands recurrence**.
Without that, anyone with a weekly standup gets double-booked every week, which
is the kind of bug nobody notices until a customer is sitting in an empty call.
"""

from datetime import timedelta

import frappe
from frappe.utils import add_to_date, get_datetime

# An Event with no end. Frappe permits it; treat it as occupying a default slot
# rather than as instantaneous, which would let us book straight over it.
ASSUMED_MINUTES = 30


def _events(user, start, end):
    from frappe.desk.doctype.event.event import get_events

    # get_events is typed `str | date` and getdate()s whatever it is given, so
    # pass whole days. It refuses another user's calendar unless the caller is a
    # System Manager; workers run as Administrator, and the API layer checks the
    # same right before a foreground caller gets here.
    return get_events(start.date() if hasattr(start, "date") else start,
                      end.date() if hasattr(end, "date") else end,
                      user=user,
                      filters=[["Event", "status", "=", "Open"]]) or []


def busy_intervals(user, start, end):
    """Sorted, merged (start, end) pairs when `user` is unavailable."""
    if not user:
        return []

    raw = []
    for ev in _events(user, start, end):
        begins = get_datetime(ev.get("starts_on"))
        if not begins:
            continue

        if ev.get("all_day"):
            # Busy for the whole local day, not for a moment at midnight.
            day = begins.date()
            raw.append((get_datetime(f"{day} 00:00:00"),
                        get_datetime(f"{day} 23:59:59")))
            continue

        ends = get_datetime(ev.get("ends_on")) if ev.get("ends_on") else None
        if not ends or ends <= begins:
            ends = add_to_date(begins, minutes=ASSUMED_MINUTES)
        raw.append((begins, ends))

    return merge(raw)


def merge(intervals):
    """Overlapping and touching intervals collapse into one."""
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda i: i[0])
    merged = [list(ordered[0])]
    for begins, ends in ordered[1:]:
        if begins <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], ends)
        else:
            merged.append([begins, ends])
    return [tuple(m) for m in merged]


def first_overlap(intervals, start, end):
    """The first interval overlapping [start, end), or None.

    Linear, because a fortnight of one person's calendar is tens of entries and
    a bisect here would be optimising the wrong thing. It matters that the
    caller then *jumps* to the end of what it hits rather than stepping.
    """
    for begins, ends in intervals:
        if begins >= end:
            break
        if ends > start:
            return (begins, ends)
    return None


def bookings_on(user, day):
    """How many Baton-made bookings this person already has that day."""
    return frappe.db.count("Baton Booking Hold", {
        "user": user,
        "status": ["in", ["Held", "Confirmed"]],
        "slot_start": ["between", [f"{day} 00:00:00", f"{day} 23:59:59"]],
    })
