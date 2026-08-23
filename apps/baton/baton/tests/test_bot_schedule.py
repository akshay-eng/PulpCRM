"""Bots that run on their own.

The point of a scheduled bot is that nothing triggers it: it wakes on its own
clock and keeps waking until someone switches it off. These tests are mostly
about the ways that could go wrong quietly -- a bot that fires twice because two
workers ticked, a bot that fires the moment it is created, a bot that forgets
what "since last time" means and reports the same deal every four hours.
"""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from baton.bots import scheduler

from .test_bot_runtime import _bot, _cleanup


def _sched(name, **kw):
    bot = _bot(name, connectors=("crm_deals",), **kw)
    return bot


class TestNextRun(FrappeTestCase):
    def tearDown(self):
        _cleanup()

    def test_every_n_hours_is_n_hours_later(self):
        bot = _sched("T Bot Every", schedule_mode="Every", every_value=4,
                     every_unit="Hours")
        base = now_datetime()
        self.assertEqual(scheduler.next_run_after(bot, base),
                         add_to_date(base, hours=4))

    def test_minutes_and_days_are_honoured(self):
        base = now_datetime()
        for unit, kwargs in (("Minutes", {"minutes": 30}), ("Days", {"days": 2})):
            bot = _sched(f"T Bot U{unit}", schedule_mode="Every",
                         every_value=30 if unit == "Minutes" else 2, every_unit=unit)
            self.assertEqual(scheduler.next_run_after(bot, base),
                             add_to_date(base, **kwargs))

    def test_a_cron_expression_gives_the_next_matching_time(self):
        bot = _sched("T Bot Cron", schedule_mode="On a cron",
                     cron_expression="0 */4 * * *")
        nxt = scheduler.next_run_after(bot, now_datetime())
        self.assertIsNotNone(nxt)
        self.assertEqual(nxt.hour % 4, 0)
        self.assertEqual(nxt.minute, 0)

    def test_an_unscheduled_bot_has_no_next_run(self):
        bot = _sched("T Bot Off", schedule_mode="Off")
        self.assertIsNone(scheduler.next_run_after(bot))

    def test_a_broken_cron_does_not_raise(self):
        """A typo in a cron box must not take the whole tick down with it."""
        bot = _sched("T Bot BadCron", schedule_mode="On a cron",
                     cron_expression="not a cron")
        self.assertIsNone(scheduler.next_run_after(bot))

    def test_zero_interval_is_refused(self):
        """Every 0 hours would mean firing on every tick, forever."""
        bot = _sched("T Bot Zero", schedule_mode="Every", every_value=0,
                     every_unit="Hours")
        self.assertIsNone(scheduler.next_run_after(bot))


class TestTick(FrappeTestCase):
    def tearDown(self):
        _cleanup()

    def test_a_new_bot_is_given_a_time_rather_than_run_immediately(self):
        bot = _sched("T Bot Fresh", schedule_mode="Every", every_value=4,
                     every_unit="Hours")
        frappe.db.set_value("Baton Bot", bot.name, "next_run_at", None)
        frappe.db.commit()

        with patch("frappe.enqueue") as enq:
            scheduler.tick()
        self.assertEqual(enq.call_count, 0)
        self.assertIsNotNone(frappe.db.get_value("Baton Bot", bot.name, "next_run_at"))

    def test_a_due_bot_runs(self):
        bot = _sched("T Bot Due", schedule_mode="Every", every_value=4,
                     every_unit="Hours")
        frappe.db.set_value("Baton Bot", bot.name,
                            "next_run_at", add_to_date(now_datetime(), hours=-1))
        frappe.db.commit()

        with patch("frappe.enqueue") as enq:
            scheduler.tick()
        started = [c for c in enq.call_args_list if c.kwargs.get("bot_name") == bot.name]
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0].kwargs["run_reason"], "schedule")

    def test_a_bot_that_is_not_due_does_not_run(self):
        bot = _sched("T Bot NotDue", schedule_mode="Every", every_value=4,
                     every_unit="Hours")
        frappe.db.set_value("Baton Bot", bot.name,
                            "next_run_at", add_to_date(now_datetime(), hours=3))
        frappe.db.commit()

        with patch("frappe.enqueue") as enq:
            scheduler.tick()
        self.assertFalse([c for c in enq.call_args_list
                          if c.kwargs.get("bot_name") == bot.name])

    def test_a_disabled_bot_never_runs(self):
        """'Until it is turned off' is the whole contract."""
        bot = _sched("T Bot Disabled", schedule_mode="Every", every_value=1,
                     every_unit="Hours", enabled=0)
        frappe.db.set_value("Baton Bot", bot.name,
                            "next_run_at", add_to_date(now_datetime(), hours=-1))
        frappe.db.commit()

        with patch("frappe.enqueue") as enq:
            scheduler.tick()
        self.assertFalse([c for c in enq.call_args_list
                          if c.kwargs.get("bot_name") == bot.name])

    def test_two_ticks_in_the_same_minute_start_one_run(self):
        """Two workers tick at once; the claim decides which one wins."""
        bot = _sched("T Bot Race", schedule_mode="Every", every_value=4,
                     every_unit="Hours")
        frappe.db.set_value("Baton Bot", bot.name,
                            "next_run_at", add_to_date(now_datetime(), hours=-1))
        frappe.db.commit()

        with patch("frappe.enqueue") as enq:
            scheduler.tick()
            scheduler.tick()
        started = [c for c in enq.call_args_list if c.kwargs.get("bot_name") == bot.name]
        self.assertEqual(len(started), 1)

    def test_the_next_time_moves_forward_after_a_run(self):
        bot = _sched("T Bot Advance", schedule_mode="Every", every_value=4,
                     every_unit="Hours")
        frappe.db.set_value("Baton Bot", bot.name,
                            "next_run_at", add_to_date(now_datetime(), hours=-1))
        frappe.db.commit()

        with patch("frappe.enqueue"):
            scheduler.tick()
        self.assertGreater(
            frappe.db.get_value("Baton Bot", bot.name, "next_run_at"), now_datetime())

    def test_the_run_is_told_when_it_last_ran(self):
        """Without this, "new since last time" has no meaning."""
        bot = _sched("T Bot Since", schedule_mode="Every", every_value=4,
                     every_unit="Hours")
        last = add_to_date(now_datetime(), hours=-4)
        frappe.db.set_value("Baton Bot", bot.name, {
            "next_run_at": add_to_date(now_datetime(), hours=-1),
            "last_run_at": last,
        })
        frappe.db.commit()

        with patch("frappe.enqueue") as enq:
            scheduler.tick()
        call = [c for c in enq.call_args_list if c.kwargs.get("bot_name") == bot.name][0]
        self.assertIn(str(last)[:16], str(call.kwargs["since"]))


class TestRescheduleOnSave(FrappeTestCase):
    def tearDown(self):
        _cleanup()

    def test_changing_the_interval_takes_effect_immediately(self):
        bot = _sched("T Bot Change", schedule_mode="Every", every_value=12,
                     every_unit="Hours")
        first = frappe.db.get_value("Baton Bot", bot.name, "next_run_at")

        bot.reload()
        bot.every_value = 1
        bot.save(ignore_permissions=True)
        frappe.db.commit()

        self.assertLess(frappe.db.get_value("Baton Bot", bot.name, "next_run_at"), first)

    def test_turning_the_schedule_off_clears_the_next_run(self):
        bot = _sched("T Bot Stop", schedule_mode="Every", every_value=4,
                     every_unit="Hours")
        bot.reload()
        bot.schedule_mode = "Off"
        bot.save(ignore_permissions=True)
        frappe.db.commit()
        self.assertIsNone(frappe.db.get_value("Baton Bot", bot.name, "next_run_at"))

    def test_run_now_makes_it_due_and_unticks_itself(self):
        bot = _sched("T Bot Now", schedule_mode="Every", every_value=4,
                     every_unit="Hours")
        bot.reload()
        bot.catch_up = 1
        bot.save(ignore_permissions=True)
        frappe.db.commit()

        row = frappe.db.get_value("Baton Bot", bot.name,
                                  ["next_run_at", "catch_up"], as_dict=True)
        self.assertLessEqual(row.next_run_at, now_datetime())
        self.assertEqual(row.catch_up, 0)


class TestScheduleWindow(FrappeTestCase):
    """The bot has to be told what "new" means, or it re-reports forever."""

    def tearDown(self):
        _cleanup()

    def test_the_prompt_names_the_last_run_time(self):
        from baton.bots.runtime import _system_prompt

        bot = _sched("T Bot Window")
        prompt = _system_prompt(bot, None, [], since="2026-08-22 10:00:00",
                                run_reason="schedule")
        self.assertIn("2026-08-22 10:00:00", prompt)
        self.assertIn("created_after", prompt)

    def test_a_first_run_says_so_rather_than_inventing_a_cutoff(self):
        from baton.bots.runtime import _system_prompt

        bot = _sched("T Bot First")
        prompt = _system_prompt(bot, None, [], since=None, run_reason="schedule")
        self.assertIn("first run", prompt)

    def test_a_triggered_run_gets_no_schedule_block(self):
        from baton.bots.runtime import _system_prompt

        bot = _sched("T Bot Trig")
        prompt = _system_prompt(bot, None, [], since=None, run_reason="trigger")
        self.assertNotIn("running on a schedule", prompt)


class TestTheClockStartsWhenYouSwitchItOn(FrappeTestCase):
    """A schedule is a promise about what happens from now."""

    def tearDown(self):
        _cleanup()

    def test_enabling_starts_the_countdown_from_that_moment(self):
        bot = _sched("T Bot Switch", schedule_mode="Every", every_value=4,
                     every_unit="Hours", enabled=0)
        self.assertIsNone(frappe.db.get_value("Baton Bot", bot.name, "next_run_at"))

        moment = now_datetime()
        bot.reload()
        bot.enabled = 1
        bot.save(ignore_permissions=True)
        frappe.db.commit()

        nxt = frappe.db.get_value("Baton Bot", bot.name, "next_run_at")
        self.assertGreaterEqual(nxt, add_to_date(moment, hours=4, seconds=-5))

    def test_switching_off_clears_the_pending_time(self):
        """Off must not leave a time that fires the instant it comes back on."""
        bot = _sched("T Bot OffClear", schedule_mode="Every", every_value=4,
                     every_unit="Hours")
        bot.reload()
        bot.enabled = 0
        bot.save(ignore_permissions=True)
        frappe.db.commit()
        self.assertIsNone(frappe.db.get_value("Baton Bot", bot.name, "next_run_at"))

    def test_a_bot_off_for_a_week_does_not_fire_immediately(self):
        bot = _sched("T Bot Week", schedule_mode="Every", every_value=4,
                     every_unit="Hours")
        bot.reload()
        bot.enabled = 0
        bot.save(ignore_permissions=True)
        bot.reload()
        bot.enabled = 1
        bot.save(ignore_permissions=True)
        frappe.db.commit()

        nxt = frappe.db.get_value("Baton Bot", bot.name, "next_run_at")
        self.assertGreater(nxt, now_datetime())

    def test_editing_a_running_bot_does_not_postpone_it(self):
        """Saving a typo fix on a 4-hour bot used to push it 4 hours away."""
        bot = _sched("T Bot Edit", schedule_mode="Every", every_value=4,
                     every_unit="Hours")
        first = frappe.db.get_value("Baton Bot", bot.name, "next_run_at")

        bot.reload()
        bot.instructions = "Slightly different wording."
        bot.save(ignore_permissions=True)
        frappe.db.commit()

        self.assertEqual(frappe.db.get_value("Baton Bot", bot.name, "next_run_at"), first)

    def test_changing_the_schedule_still_takes_effect_at_once(self):
        bot = _sched("T Bot Reshape", schedule_mode="Every", every_value=12,
                     every_unit="Hours")
        first = frappe.db.get_value("Baton Bot", bot.name, "next_run_at")

        bot.reload()
        bot.every_value = 1
        bot.save(ignore_permissions=True)
        frappe.db.commit()

        self.assertLess(frappe.db.get_value("Baton Bot", bot.name, "next_run_at"), first)
