"""Waking the follow-up bot once a booked meeting has ended."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from baton.scheduling import followup

from .test_engine import _lead

BOT_NAME = "Meeting Follow-up"


def _meeting(reference_name, reference_doctype="CRM Lead", ends_minutes_ago=30):
    ends = add_to_date(now_datetime(), minutes=-ends_minutes_ago)
    return frappe.get_doc({
        "doctype": "Event",
        "subject": "Intro call",
        "event_category": "Meeting",
        "event_type": "Private",
        "starts_on": add_to_date(ends, minutes=-30),
        "ends_on": ends,
        "reference_doctype": reference_doctype,
        "reference_docname": reference_name,
    }).insert(ignore_permissions=True)


class TestFollowupTick(FrappeTestCase):
    def setUp(self):
        self.lead = _lead()
        self._was_enabled = frappe.db.get_value("Baton Bot", BOT_NAME, "enabled")
        if self._was_enabled is not None:
            frappe.db.set_value("Baton Bot", BOT_NAME, "enabled", 1)

    def tearDown(self):
        if self._was_enabled is not None:
            frappe.db.set_value("Baton Bot", BOT_NAME, "enabled", self._was_enabled)
        frappe.db.rollback()

    def test_a_meeting_that_ended_is_queued(self):
        if self._was_enabled is None:
            self.skipTest(f"{BOT_NAME} is not installed on this site")
        ev = _meeting(self.lead.name)

        with patch("frappe.enqueue") as enqueue:
            followup.tick()

        calls = [c for c in enqueue.call_args_list if c.kwargs.get("bot_name") == BOT_NAME]
        self.assertTrue(calls, "did not queue a run for the ended meeting")
        self.assertEqual(calls[0].kwargs["reference_doctype"], "CRM Lead")
        self.assertEqual(calls[0].kwargs["reference_name"], self.lead.name)

    def test_a_meeting_that_has_not_ended_yet_is_not_queued(self):
        if self._was_enabled is None:
            self.skipTest(f"{BOT_NAME} is not installed on this site")
        _meeting(self.lead.name, ends_minutes_ago=-60)  # ends an hour from now

        with patch("frappe.enqueue") as enqueue:
            followup.tick()

        calls = [c for c in enqueue.call_args_list if c.kwargs.get("bot_name") == BOT_NAME]
        self.assertFalse(calls)

    def test_the_same_meeting_is_not_queued_twice(self):
        if self._was_enabled is None:
            self.skipTest(f"{BOT_NAME} is not installed on this site")
        _meeting(self.lead.name)

        with patch("frappe.enqueue") as enqueue:
            followup.tick()
            followup.tick()

        calls = [c for c in enqueue.call_args_list if c.kwargs.get("bot_name") == BOT_NAME]
        self.assertEqual(len(calls), 1)

    def test_nothing_happens_when_the_bot_is_disabled(self):
        if self._was_enabled is None:
            self.skipTest(f"{BOT_NAME} is not installed on this site")
        frappe.db.set_value("Baton Bot", BOT_NAME, "enabled", 0)
        _meeting(self.lead.name)

        with patch("frappe.enqueue") as enqueue:
            followup.tick()  # must not raise
        enqueue.assert_not_called()

    def test_missing_bot_does_not_raise(self):
        with patch("frappe.db.exists", return_value=False):
            followup.tick()  # must not raise
