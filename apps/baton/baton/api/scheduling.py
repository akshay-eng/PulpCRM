"""Availability and service configuration for the Settings pane."""

import json

import frappe
from frappe import _

AVAILABILITY_FIELDS = (
    "title", "enabled", "user", "timezone", "google_calendar", "holiday_list",
    "slot_minutes", "buffer_before_minutes", "buffer_after_minutes",
    "min_notice_minutes", "max_days_ahead", "max_bookings_per_day",
)
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@frappe.whitelist()
def get_config():
    availabilities = []
    for name in frappe.get_all("Baton Availability", pluck="name", order_by="title"):
        doc = frappe.get_doc("Baton Availability", name)
        row = {f: doc.get(f) for f in AVAILABILITY_FIELDS}
        row["name"] = doc.name
        row["working_hours"] = [
            {"workday": d.workday,
             "start_time": str(d.start_time or ""),
             "end_time": str(d.end_time or "")}
            for d in doc.working_hours
        ]
        availabilities.append(row)

    return {
        "availabilities": availabilities,
        "services": frappe.get_all(
            "Baton Service",
            fields=["name", "service_name", "enabled", "duration_minutes",
                    "default_availability", "description"],
            order_by="service_name"),
        "weekdays": list(WEEKDAYS),
        "holiday_lists": frappe.get_all("CRM Holiday List", pluck="name"),
        "timezone": frappe.utils.get_system_timezone(),
    }


@frappe.whitelist()
def save_availability(data):
    frappe.only_for(["System Manager", "Sales Manager"])
    if isinstance(data, str):
        data = json.loads(data)

    name = data.get("name")
    if name and frappe.db.exists("Baton Availability", name):
        doc = frappe.get_doc("Baton Availability", name)
        doc.check_permission("write")
    else:
        doc = frappe.new_doc("Baton Availability")

    for f in AVAILABILITY_FIELDS:
        if f in data:
            doc.set(f, data[f])

    doc.set("working_hours", [])
    seen = set()
    for row in data.get("working_hours") or []:
        day = row.get("workday")
        # One window per day: two rows for Monday would silently offer slots
        # from whichever the loop saw last.
        if not day or day in seen:
            continue
        if not (row.get("start_time") and row.get("end_time")):
            continue
        if row["start_time"] >= row["end_time"]:
            frappe.throw(_("{0}: the end time must be after the start time.").format(day))
        seen.add(day)
        doc.append("working_hours", {
            "workday": day,
            "start_time": row["start_time"],
            "end_time": row["end_time"],
        })

    doc.save()
    frappe.db.commit()
    return doc.name


@frappe.whitelist()
def save_service(data):
    frappe.only_for(["System Manager", "Sales Manager"])
    if isinstance(data, str):
        data = json.loads(data)

    name = data.get("name")
    if name and frappe.db.exists("Baton Service", name):
        doc = frappe.get_doc("Baton Service", name)
    else:
        doc = frappe.new_doc("Baton Service")

    for f in ("service_name", "enabled", "duration_minutes",
              "default_availability", "description", "synonyms"):
        if f in data:
            doc.set(f, data[f])
    doc.save()
    frappe.db.commit()
    return doc.name


@frappe.whitelist()
def preview_slots(availability, duration=30, count=5):
    """What would be offered right now. Reads another user's calendar, so gated."""
    frappe.only_for(["System Manager", "Sales Manager"])
    from baton.scheduling import slots as slot_mod
    from baton.scheduling import workhours as wh

    doc = frappe.get_doc("Baton Availability", availability)
    tz = wh.tz_of(doc)
    found = slot_mod.free_slots(doc, int(duration), limit=int(count), user=doc.user)
    return [{"start": str(s), "label": wh.label(s, tz)} for s in found[: int(count)]]
