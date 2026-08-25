"""The deterministic no-reply retry ladder, in isolation from the bot loop
that drives it."""

import datetime

from frappe.tests.utils import FrappeTestCase
from frappe.utils import get_datetime

from baton.bots import cadence


class TestSecondsUntilNextHour(FrappeTestCase):
    def test_before_the_hour_rolls_to_today(self):
        now = get_datetime("2026-08-25 06:00:00")
        seconds = cadence.seconds_until_next_hour(9, now=now)
        target = now + datetime.timedelta(seconds=seconds)
        self.assertEqual(target, get_datetime("2026-08-25 09:00:00"))

    def test_after_the_hour_rolls_to_tomorrow(self):
        now = get_datetime("2026-08-25 14:00:00")
        seconds = cadence.seconds_until_next_hour(9, now=now)
        target = now + datetime.timedelta(seconds=seconds)
        self.assertEqual(target, get_datetime("2026-08-26 09:00:00"))

    def test_exactly_at_the_hour_rolls_to_tomorrow(self):
        """<= , not < -- the hour arriving is the deadline passing, not
        still ahead of it."""
        now = get_datetime("2026-08-25 09:00:00")
        seconds = cadence.seconds_until_next_hour(9, now=now)
        target = now + datetime.timedelta(seconds=seconds)
        self.assertEqual(target, get_datetime("2026-08-26 09:00:00"))

    def test_never_returns_less_than_a_minute(self):
        now = get_datetime("2026-08-25 08:59:59")
        self.assertGreaterEqual(cadence.seconds_until_next_hour(9, now=now), 60)


class TestAdvance(FrappeTestCase):
    def test_sequences_through_all_rungs_then_exhausts(self):
        state = {"vars": {}}

        rung1, note1 = cadence.advance(state)
        self.assertEqual(rung1["channel"], "WhatsApp")
        self.assertEqual(state["vars"]["followup_attempt"], 1)
        self.assertIn("Attempt 1 of 3", note1)

        rung2, note2 = cadence.advance(state)
        self.assertEqual(rung2["channel"], "WhatsApp")
        self.assertEqual(state["vars"]["followup_attempt"], 2)

        rung3, note3 = cadence.advance(state)
        self.assertEqual(rung3["channel"], "Email")
        self.assertEqual(state["vars"]["followup_attempt"], 3)

        rung4, note4 = cadence.advance(state)
        self.assertIsNone(rung4)
        self.assertIsNone(note4)

    def test_each_advance_sets_the_pending_wait_for_the_next_wait_for_reply(self):
        state = {"vars": {}}
        cadence.advance(state)
        pending = state["vars"]["_cadence_pending"]
        self.assertEqual(pending["channel"], "WhatsApp")
        self.assertGreater(pending["wait_seconds"], 0)

    def test_the_third_rung_is_email_with_a_day_long_wait(self):
        state = {"vars": {"followup_attempt": 2}}
        rung, _ = cadence.advance(state)
        self.assertEqual(rung["channel"], "Email")
        self.assertEqual(state["vars"]["_cadence_pending"]["wait_seconds"], 24 * 3600)
