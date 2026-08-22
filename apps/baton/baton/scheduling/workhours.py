"""Working hours, holidays and timezones.

CRM's own `CRMServiceLevelAgreement` has equivalents of these, but they are AGPL
and they walk forward one second at a time -- fine for an SLA delta, unusable
for generating slots across a fortnight. These are written fresh, work on the
slot grid, and are timezone-aware, which CRM's are not.
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import get_datetime, get_system_timezone

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _as_time(value):
    """Frappe hands Time fields back as timedelta as often as time."""
    if isinstance(value, timedelta):
        total = int(value.total_seconds())
        return time(total // 3600 % 24, total % 3600 // 60, total % 60)
    if isinstance(value, time):
        return value
    if isinstance(value, str):
        parts = [int(p) for p in value.split(":")]
        while len(parts) < 3:
            parts.append(0)
        return time(*parts[:3])
    return None


def working_hours(availability):
    """{weekday name: (start_time, end_time)} for the days that are worked."""
    out = {}
    for row in availability.get("working_hours") or []:
        start, end = _as_time(row.start_time), _as_time(row.end_time)
        if row.workday and start and end and start < end:
            out[row.workday] = (start, end)
    return out


def holiday_dates(holiday_list):
    if not holiday_list or not frappe.db.exists("CRM Holiday List", holiday_list):
        return set()
    return {
        get_datetime(d).date() if not hasattr(d, "year") else d
        for d in frappe.get_all("CRM Holiday",
                                filters={"parent": holiday_list}, pluck="date")
        if d
    }


def tz_of(availability):
    name = availability.get("timezone") or get_system_timezone()
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo(get_system_timezone())


def to_system(day, clock, tz):
    """A local wall-clock time on `day`, expressed in naive system time.

    Returns None when that wall-clock time does not exist -- on the morning the
    clocks go forward, 09:00 may simply not happen, and offering a slot then
    would produce a meeting nobody can attend. On the way back an hour occurs
    twice; `fold=0` takes the first, which is the earlier real instant.
    """
    local = datetime.combine(day, clock).replace(tzinfo=tz, fold=0)

    # If the zone shifted this stamp, the wall-clock time was skipped.
    if local.astimezone(ZoneInfo("UTC")).astimezone(tz).replace(tzinfo=tz) != local:
        return None

    system = local.astimezone(ZoneInfo(get_system_timezone()))
    return system.replace(tzinfo=None)


def label(dt_system, tz):
    """A time a customer can act on: local, with the zone named.

    Never quote a bare time to someone whose zone you have not stated.
    """
    aware = dt_system.replace(tzinfo=ZoneInfo(get_system_timezone())).astimezone(tz)
    return aware.strftime("%a %d %b, %-I:%M %p ") + (aware.tzname() or "")
