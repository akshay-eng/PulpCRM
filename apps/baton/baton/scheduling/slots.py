"""Turning working hours into offerable times.

The whole algorithm is: walk the slot grid inside each working window, and when
a slot collides with something, jump to the end of what it collided with rather
than stepping through it. A fortnight of half-hour slots is a couple of hundred
probes.

CRM's `calc_elapsed_time` does the same job by adding one second at a time --
about 1.2 million iterations over the same fortnight. That is why none of this
reuses it.
"""

from datetime import timedelta

import frappe
from frappe.utils import add_to_date, now_datetime

from baton.scheduling import busy as busy_mod
from baton.scheduling import workhours as wh


def _align_up(dt, minutes):
    grid = minutes * 60
    seconds = dt.hour * 3600 + dt.minute * 60 + dt.second
    over = seconds % grid
    if not over:
        return dt.replace(microsecond=0)
    return (dt + timedelta(seconds=grid - over)).replace(second=0, microsecond=0)


def free_slots(availability, duration_minutes, limit=3, user=None, from_dt=None):
    """The next `limit` bookable starts, as naive system datetimes.

    Oversamples internally: between offering a slot and someone accepting it,
    minutes pass and the earliest one may be taken.
    """
    user = user or availability.get("user")
    tz = wh.tz_of(availability)
    hours = wh.working_hours(availability)
    if not hours:
        return []

    holidays = wh.holiday_dates(availability.get("holiday_list"))
    grid = int(availability.get("slot_minutes") or 30)
    before = int(availability.get("buffer_before_minutes") or 0)
    after = int(availability.get("buffer_after_minutes") or 0)
    notice = int(availability.get("min_notice_minutes") or 0)
    horizon = int(availability.get("max_days_ahead") or 14)
    per_day_cap = int(availability.get("max_bookings_per_day") or 0)

    start_at = (from_dt or now_datetime()) + timedelta(minutes=notice)
    end_at = add_to_date(start_at, days=horizon)

    # One query for the whole horizon, not one per day.
    occupied = busy_mod.busy_intervals(user, start_at, end_at) if user else []

    duration = timedelta(minutes=duration_minutes)
    out = []
    day = start_at.date()
    last_day = end_at.date()

    while day <= last_day and len(out) < limit * 3:
        window = hours.get(wh.WEEKDAYS[day.weekday()])
        if not window or day in holidays:
            day += timedelta(days=1)
            continue

        if per_day_cap and user and busy_mod.bookings_on(user, day) >= per_day_cap:
            day += timedelta(days=1)
            continue

        opens = wh.to_system(day, window[0], tz)
        closes = wh.to_system(day, window[1], tz)
        if not opens or not closes:
            # The clocks moved through this window; skip rather than guess.
            day += timedelta(days=1)
            continue

        cursor = _align_up(max(opens, start_at), grid)
        while cursor + duration + timedelta(minutes=after) <= closes:
            probe_start = cursor - timedelta(minutes=before)
            probe_end = cursor + duration + timedelta(minutes=after)
            hit = busy_mod.first_overlap(occupied, probe_start, probe_end)
            if hit:
                # Jump past the whole conflict instead of inching through it.
                cursor = _align_up(hit[1] + timedelta(minutes=before), grid)
                continue
            out.append(cursor)
            if len(out) >= limit * 3:
                break
            cursor += timedelta(minutes=grid)

        day += timedelta(days=1)

    return out[: limit * 3]


def resolve_availability(reference_doctype=None, reference_name=None,
                         service=None, explicit=None):
    """Which schedule applies. Four steps, no guessing.

    node config -> the service's default -> the record owner's own -> the
    org-wide fallback (the one with no user).
    """
    if explicit and frappe.db.exists("Baton Availability", explicit):
        return frappe.get_doc("Baton Availability", explicit)

    if service and frappe.db.exists("Baton Service", service):
        svc = frappe.get_cached_doc("Baton Service", service)
        if svc.default_availability:
            return frappe.get_doc("Baton Availability", svc.default_availability)

    owner = None
    if reference_doctype and reference_name:
        field = {"CRM Lead": "lead_owner", "CRM Deal": "deal_owner"}.get(reference_doctype)
        if field:
            owner = frappe.db.get_value(reference_doctype, reference_name, field)
    if owner:
        mine = frappe.get_all("Baton Availability",
                              filters={"user": owner, "enabled": 1}, pluck="name")
        if mine:
            return frappe.get_doc("Baton Availability", mine[0])

    shared = frappe.get_all("Baton Availability",
                            filters={"user": ["in", ["", None]], "enabled": 1},
                            pluck="name")
    return frappe.get_doc("Baton Availability", shared[0]) if shared else None
