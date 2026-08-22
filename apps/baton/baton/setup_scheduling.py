"""Availability, services, and booking holds.

Reuses CRM's own scheduling primitives rather than inventing parallel ones:
`working_hours` is a table of CRM Service Day, and `holiday_list` links CRM
Holiday List. Both already exist, already have a settings UI, and are already
what an admin edits for SLA policies -- a second weekday table would just be a
second thing to keep in step.

What CRM does not have is a timezone on a schedule, so `Baton Availability`
adds one. Working hours mean nothing without it once you are quoting times to a
customer.
"""

import frappe

from baton.setup_phase1 import _add_fields, _doctype, _extend_select


def install():
    _doctype(
        "Baton Availability",
        [
            {"fieldname": "title", "fieldtype": "Data", "label": "Title", "reqd": 1,
             "unique": 1, "in_list_view": 1},
            {"fieldname": "enabled", "fieldtype": "Check", "label": "Enabled", "default": "1"},
            {"fieldname": "user", "fieldtype": "Link", "label": "For user", "options": "User",
             "in_list_view": 1,
             "description": "Blank makes this the fallback for everyone."},
            {"fieldname": "col_av", "fieldtype": "Column Break"},
            {"fieldname": "timezone", "fieldtype": "Data", "label": "Timezone",
             "description": "Working hours are read in this zone, and times quoted to "
                            "customers are labelled with it."},
            {"fieldname": "google_calendar", "fieldtype": "Link", "label": "Google Calendar",
             "options": "Google Calendar",
             "description": "Optional. Enables two-way sync and a Meet link."},

            {"fieldname": "sec_hours", "fieldtype": "Section Break", "label": "Working hours"},
            {"fieldname": "working_hours", "fieldtype": "Table", "label": "Working hours",
             "options": "CRM Service Day"},
            {"fieldname": "holiday_list", "fieldtype": "Link", "label": "Holiday list",
             "options": "CRM Holiday List"},

            {"fieldname": "sec_slots", "fieldtype": "Section Break", "label": "Slots"},
            {"fieldname": "slot_minutes", "fieldtype": "Int", "label": "Slot every (minutes)",
             "default": "30"},
            {"fieldname": "buffer_before_minutes", "fieldtype": "Int", "label": "Buffer before",
             "default": "0"},
            {"fieldname": "buffer_after_minutes", "fieldtype": "Int", "label": "Buffer after",
             "default": "10"},
            {"fieldname": "col_slots", "fieldtype": "Column Break"},
            {"fieldname": "min_notice_minutes", "fieldtype": "Int", "label": "Minimum notice",
             "default": "120",
             "description": "Never offer a slot sooner than this."},
            {"fieldname": "max_days_ahead", "fieldtype": "Int", "label": "Look ahead (days)",
             "default": "14"},
            {"fieldname": "max_bookings_per_day", "fieldtype": "Int",
             "label": "Max bookings per day", "default": "0",
             "description": "0 means no limit."},
        ],
        autoname="field:title",
        title_field="title",
    )

    _doctype(
        "Baton Service",
        [
            {"fieldname": "service_name", "fieldtype": "Data", "label": "Service", "reqd": 1,
             "unique": 1, "in_list_view": 1},
            {"fieldname": "enabled", "fieldtype": "Check", "label": "Enabled", "default": "1"},
            {"fieldname": "col_s", "fieldtype": "Column Break"},
            {"fieldname": "duration_minutes", "fieldtype": "Int", "label": "Meeting length",
             "default": "30", "in_list_view": 1},
            {"fieldname": "default_availability", "fieldtype": "Link", "label": "Availability",
             "options": "Baton Availability"},
            {"fieldname": "sec_d", "fieldtype": "Section Break"},
            {"fieldname": "description", "fieldtype": "Small Text", "label": "Description"},
            {"fieldname": "synonyms", "fieldtype": "Data", "label": "Also called"},
        ],
        autoname="field:service_name",
        title_field="service_name",
    )

    # The hold is the entire concurrency control. `hold_key` is unique while a
    # hold is live and NULL once released -- MariaDB allows unlimited NULLs in a
    # unique index, so "at most one live hold per person per slot" falls out of
    # the schema instead of needing a lock.
    _doctype(
        "Baton Booking Hold",
        [
            {"fieldname": "hold_key", "fieldtype": "Data", "label": "Hold key",
             "unique": 1, "read_only": 1, "no_copy": 1},
            {"fieldname": "status", "fieldtype": "Select", "label": "Status",
             "options": "Held\nConfirmed\nReleased", "default": "Held", "in_list_view": 1},
            {"fieldname": "user", "fieldtype": "Link", "label": "With", "options": "User",
             "in_list_view": 1},
            {"fieldname": "col_h", "fieldtype": "Column Break"},
            {"fieldname": "slot_start", "fieldtype": "Datetime", "label": "From",
             "in_list_view": 1},
            {"fieldname": "slot_end", "fieldtype": "Datetime", "label": "To"},
            {"fieldname": "expires_at", "fieldtype": "Datetime", "label": "Hold expires"},

            {"fieldname": "sec_ref", "fieldtype": "Section Break"},
            {"fieldname": "reference_doctype", "fieldtype": "Link", "label": "Reference Type",
             "options": "DocType"},
            {"fieldname": "reference_name", "fieldtype": "Dynamic Link", "label": "Reference",
             "options": "reference_doctype"},
            {"fieldname": "col_r", "fieldtype": "Column Break"},
            {"fieldname": "service", "fieldtype": "Link", "label": "Service",
             "options": "Baton Service"},
            {"fieldname": "workflow_run", "fieldtype": "Link", "label": "Workflow run",
             "options": "Baton Workflow Run"},
            {"fieldname": "event", "fieldtype": "Link", "label": "Event", "options": "Event"},
        ],
    )

    _extend_select("Baton Workflow Node", "node_type", ["Offer Slots", "Book Appointment"])

    frappe.db.commit()
    print("Scheduling doctypes ready.")


def seed_default():
    if not frappe.db.exists("Baton Availability", "Default hours"):
        frappe.get_doc({
            "doctype": "Baton Availability",
            "title": "Default hours",
            "enabled": 1,
            "timezone": frappe.utils.get_system_timezone(),
            # Mon-Fri 09:00-17:00, the same default CRM's own SLA setup ships.
            "working_hours": [
                {"workday": d, "start_time": "09:00:00", "end_time": "17:00:00"}
                for d in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
            ],
        }).insert(ignore_permissions=True)
        print("  + Default hours (Mon-Fri 09:00-17:00)")
    else:
        print("  = Default hours exists")

    if not frappe.db.exists("Baton Service", "Intro call"):
        frappe.get_doc({
            "doctype": "Baton Service",
            "service_name": "Intro call",
            "enabled": 1,
            "duration_minutes": 30,
            "default_availability": "Default hours",
            "description": "A short introductory call.",
        }).insert(ignore_permissions=True)
        print("  + Intro call (30 min)")
    else:
        print("  = Intro call exists")

    frappe.db.commit()


def install_all():
    install()
    seed_default()
