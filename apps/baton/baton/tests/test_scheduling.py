"""Slot generation, conflict safety and booking.

The failures worth guarding here are the quiet ones: a slot offered over a
recurring meeting, a double-booking because an Event ended up owned by the
wrong user, and a slot that does not exist because the clocks moved.
"""

from datetime import timedelta

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, get_datetime, now_datetime

from baton.scheduling import book as booking
from baton.scheduling import busy as busy_mod
from baton.scheduling import slots as slot_mod
from baton.scheduling import workhours as wh

from .test_engine import _delete_test_leads, _lead

AVAIL = "T Sched Availability"


def _availability(**kw):
    if frappe.db.exists("Baton Availability", AVAIL):
        frappe.delete_doc("Baton Availability", AVAIL, force=True, ignore_permissions=True)
    values = {
        "doctype": "Baton Availability",
        "title": AVAIL,
        "enabled": 1,
        "timezone": frappe.utils.get_system_timezone(),
        "slot_minutes": 30,
        "buffer_before_minutes": 0,
        "buffer_after_minutes": 0,
        "min_notice_minutes": 0,
        "max_days_ahead": 7,
        "working_hours": [
            {"workday": d, "start_time": "09:00:00", "end_time": "17:00:00"}
            for d in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
        ],
    }
    values.update(kw)
    doc = frappe.get_doc(values).insert(ignore_permissions=True)
    frappe.db.commit()
    return doc


def _next_monday_9am():
    day = now_datetime().date()
    while day.weekday() != 0:
        day += timedelta(days=1)
    if day == now_datetime().date():
        day += timedelta(days=7)
    return get_datetime(f"{day} 09:00:00")


class TestWorkingHours(FrappeTestCase):
    def test_timedelta_times_are_understood(self):
        """Frappe returns Time fields as timedelta as often as time."""
        self.assertEqual(wh._as_time(timedelta(hours=9, minutes=30)).hour, 9)
        self.assertEqual(wh._as_time(timedelta(hours=9, minutes=30)).minute, 30)
        self.assertEqual(wh._as_time("17:00:00").hour, 17)

    def test_only_sane_windows_are_kept(self):
        av = _availability(working_hours=[
            {"workday": "Monday", "start_time": "09:00:00", "end_time": "17:00:00"},
            {"workday": "Tuesday", "start_time": "17:00:00", "end_time": "09:00:00"},
        ])
        hours = wh.working_hours(av)
        self.assertIn("Monday", hours)
        self.assertNotIn("Tuesday", hours, "an end before its start is not a window")

    def test_a_quoted_time_names_its_zone(self):
        av = _availability()
        text = wh.label(_next_monday_9am(), wh.tz_of(av))
        self.assertRegex(text, r"[A-Z]{2,5}$")


class TestBusyIntervals(FrappeTestCase):
    def test_overlapping_intervals_merge(self):
        a = get_datetime("2026-09-01 09:00:00")
        merged = busy_mod.merge([
            (a, add_to_date(a, hours=1)),
            (add_to_date(a, minutes=30), add_to_date(a, hours=2)),
            (add_to_date(a, hours=4), add_to_date(a, hours=5)),
        ])
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0][1], add_to_date(a, hours=2))

    def test_first_overlap_finds_the_collision(self):
        a = get_datetime("2026-09-01 09:00:00")
        busy = [(a, add_to_date(a, hours=1))]
        self.assertIsNotNone(
            busy_mod.first_overlap(busy, add_to_date(a, minutes=30), add_to_date(a, minutes=90)))
        self.assertIsNone(
            busy_mod.first_overlap(busy, add_to_date(a, hours=2), add_to_date(a, hours=3)))


class TestSlotGeneration(FrappeTestCase):
    def tearDown(self):
        _delete_test_leads()

    def test_it_offers_slots_inside_working_hours_only(self):
        av = _availability()
        found = slot_mod.free_slots(av, 30, limit=5)
        self.assertTrue(found)
        for slot in found:
            self.assertIn(wh.WEEKDAYS[slot.weekday()],
                          ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday"))
            self.assertGreaterEqual(slot.hour, 9)
            self.assertLess(slot.hour, 17)

    def test_a_slot_never_runs_past_closing(self):
        av = _availability(working_hours=[
            {"workday": d, "start_time": "09:00:00", "end_time": "10:00:00"}
            for d in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
        ])
        for slot in slot_mod.free_slots(av, 45, limit=5):
            self.assertLessEqual((slot + timedelta(minutes=45)).hour, 10)

    def test_a_holiday_is_skipped(self):
        target = _next_monday_9am().date()
        listname = "T Sched Holidays"
        if frappe.db.exists("CRM Holiday List", listname):
            frappe.delete_doc("CRM Holiday List", listname, force=True, ignore_permissions=True)
        frappe.get_doc({
            "doctype": "CRM Holiday List",
            "holiday_list_name": listname,
            "from_date": add_to_date(now_datetime(), days=-1),
            "to_date": add_to_date(now_datetime(), days=30),
            "holidays": [{"date": target, "description": "Test holiday"}],
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        av = _availability(holiday_list=listname)
        self.assertFalse(
            [s for s in slot_mod.free_slots(av, 30, limit=20) if s.date() == target],
            "offered a slot on a holiday")

    def test_minimum_notice_is_respected(self):
        av = _availability(min_notice_minutes=6000)  # ~4 days
        earliest = min(slot_mod.free_slots(av, 30, limit=3))
        self.assertGreater(earliest, add_to_date(now_datetime(), days=3))

    def test_it_does_not_walk_a_second_at_a_time(self):
        """A fortnight of slots must be a couple of hundred probes, not millions."""
        import time as timing

        av = _availability(max_days_ahead=14)
        started = timing.time()
        slot_mod.free_slots(av, 30, limit=3)
        self.assertLess(timing.time() - started, 2.0)


def _clear_holds():
    """Holds are committed, so a previous run's leftovers would collide."""
    for h in frappe.get_all("Baton Booking Hold", pluck="name"):
        frappe.delete_doc("Baton Booking Hold", h, force=True, ignore_permissions=True)
    frappe.db.commit()


class TestHoldsAreTheConcurrencyControl(FrappeTestCase):
    def setUp(self):
        _clear_holds()

    def tearDown(self):
        _delete_test_leads()

    def test_two_runs_cannot_hold_the_same_slot(self):
        start = _next_monday_9am()
        end = add_to_date(start, minutes=30)

        first, why1 = booking.hold("Administrator", start, end)
        second, why2 = booking.hold("Administrator", start, end)

        self.assertIsNotNone(first)
        self.assertIsNone(second, "two holds on one slot")
        self.assertIn("taken", why2)

    def test_releasing_frees_the_slot_again(self):
        start = _next_monday_9am()
        end = add_to_date(start, minutes=30)

        first, _ = booking.hold("Administrator", start, end)
        booking.release(first.name)
        again, why = booking.hold("Administrator", start, end)
        self.assertIsNotNone(again, f"slot stayed locked after release: {why}")

    def test_expired_holds_are_swept(self):
        start = _next_monday_9am()
        held, _ = booking.hold("Administrator", start, add_to_date(start, minutes=30))
        frappe.db.set_value("Baton Booking Hold", held.name, "expires_at",
                            add_to_date(now_datetime(), minutes=-1))
        frappe.db.commit()

        booking.release_expired_holds()
        self.assertEqual(
            frappe.db.get_value("Baton Booking Hold", held.name, "status"), "Released")


class TestConfirm(FrappeTestCase):
    def setUp(self):
        _clear_holds()

    def tearDown(self):
        _delete_test_leads()

    def test_the_event_is_owned_by_the_rep(self):
        """get_events filters on owner; the wrong owner means we re-offer this slot."""
        lead = _lead()
        start = _next_monday_9am()
        held, _ = booking.hold("Administrator", start, add_to_date(start, minutes=30),
                               reference_doctype="CRM Lead", reference_name=lead.name)
        event = booking.confirm(held, subject="T Sched Call")
        self.addCleanup(frappe.delete_doc, "Event", event, force=True, ignore_permissions=True)

        self.assertEqual(frappe.db.get_value("Event", event, "owner"), "Administrator")
        self.assertEqual(
            frappe.db.get_value("Baton Booking Hold", held.name, "status"), "Confirmed")

    def test_google_sync_is_off_at_insert(self):
        """A Google outage must not roll back a booking already promised."""
        lead = _lead()
        start = add_to_date(_next_monday_9am(), minutes=30)
        held, _ = booking.hold("Administrator", start, add_to_date(start, minutes=30),
                               reference_doctype="CRM Lead", reference_name=lead.name)
        event = booking.confirm(held, subject="T Sched Call 2")
        self.addCleanup(frappe.delete_doc, "Event", event, force=True, ignore_permissions=True)

        self.assertEqual(
            frappe.db.get_value("Event", event, "sync_with_google_calendar"), 0)

    def test_a_confirmed_slot_is_no_longer_offered(self):
        lead = _lead()
        av = _availability(user="Administrator")
        first = slot_mod.free_slots(av, 30, limit=1, user="Administrator")[0]

        held, _ = booking.hold("Administrator", first, add_to_date(first, minutes=30),
                               reference_doctype="CRM Lead", reference_name=lead.name)
        event = booking.confirm(held, subject="T Sched Blocking")
        self.addCleanup(frappe.delete_doc, "Event", event, force=True, ignore_permissions=True)

        again = slot_mod.free_slots(av, 30, limit=3, user="Administrator")
        self.assertNotIn(first, again, "offered a slot that was just booked")


def tearDownModule():
    for name in frappe.get_all("Baton Availability",
                               filters={"title": ["like", "T Sched%"]}, pluck="name"):
        frappe.delete_doc("Baton Availability", name, force=True, ignore_permissions=True)
    for name in frappe.get_all("CRM Holiday List",
                               filters={"name": ["like", "T Sched%"]}, pluck="name"):
        frappe.delete_doc("CRM Holiday List", name, force=True, ignore_permissions=True)
    for name in frappe.get_all("Baton Booking Hold", pluck="name"):
        frappe.delete_doc("Baton Booking Hold", name, force=True, ignore_permissions=True)
    # Events are committed by confirm(), so addCleanup's rollback cannot remove
    # them -- and a stray one silently blocks that slot in every later run.
    for name in frappe.get_all("Event", filters={"subject": ["like", "T Sched%"]},
                               pluck="name"):
        frappe.delete_doc("Event", name, force=True, ignore_permissions=True)
    _delete_test_leads()
    frappe.db.commit()
