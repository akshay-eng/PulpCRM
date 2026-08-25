"""Waking the follow-up bot once a booked meeting has ended."""

import json
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


class TestMeetingFollowupAsksAssignee(FrappeTestCase):
    """End-to-end: ask_assignee -> resume with the assignee's own reply ->
    act on it. Not scheduling/followup.py's concern (that's covered above)
    -- this is the bot's own conversational behavior once it's running."""

    def setUp(self):
        from baton.bots import runtime, tools

        from .test_bot_runtime import _bot, _cleanup, _replies

        self.runtime, self.tools = runtime, tools
        self._bot, self._cleanup, self._replies = _bot, _cleanup, _replies

        self.lead = _lead()
        self.lead.db_set("_assign", json.dumps(["Administrator"]))
        self._original_mobile = frappe.db.get_value("User", "Administrator", "mobile_no")
        frappe.db.set_value("User", "Administrator", "mobile_no", "+919000000005")
        # A distinct name, deliberately -- BOT_NAME is the real production
        # bot this site actually runs; _bot() deletes-and-recreates whatever
        # name it's given, so reusing BOT_NAME here would destroy it.
        self.bot = _bot("T Bot Meeting Followup", connectors=(
            "crm_leads", "crm_deals", "whatsapp", "crm_notes", "crm_tasks",
            "crm_comments", "crm_field_options"))

    def tearDown(self):
        frappe.db.set_value("User", "Administrator", "mobile_no", self._original_mobile)
        self._cleanup()

    def _ask_then_resume(self, assignee_reply):
        ask_script = self._replies(
            {"tool": "ask_assignee", "args": {"message": "How did it go?"}, "done": False})
        with patch("baton.bots.runtime.chat_json", side_effect=ask_script), \
             patch("baton.bots.catalog._whatsapp_ready", return_value=(True, "OpenWA")), \
             patch("baton.workflow.actions.whatsapp.send", return_value={"sent": True}):
            run = self.runtime.run_bot(self.bot.name, doc=self.lead)

        msg = frappe.get_doc({
            "doctype": "WhatsApp Message", "type": "Incoming", "to": "911234500000",
            "message": assignee_reply, "content_type": "text", "baton_author": "contact",
        }).insert(ignore_permissions=True)
        return run, msg

    def test_happy_path_converts_the_lead(self):
        run, msg = self._ask_then_resume("Went great, they're ready to move forward")

        resume_script = self._replies(
            {"thought": "Converting.", "tool": "convert_lead", "args": {}, "done": False},
            {"done": True, "summary": "Converted and logged."})
        with patch("baton.bots.runtime.chat_json", side_effect=resume_script):
            self.runtime.run_bot(self.bot.name, resume_run=run, inbound_message=msg.name,
                                 inbound_channel="WhatsApp", inbound_from_assignee=True,
                                 run_reason="reply")

        self.lead.reload()
        self.assertTrue(self.lead.converted)

    def test_unhappy_path_disqualifies_and_emits_the_event(self):
        run, msg = self._ask_then_resume("Not interested, going with a competitor")

        resume_script = self._replies(
            {"thought": "Marking unqualified.", "tool": "update_leads",
             "args": {"name": self.lead.name,
                      "values": {"status": "Junk", "lost_reason": "Competition"}},
             "done": False},
            {"done": True, "summary": "Marked unqualified."})
        with patch("baton.bots.runtime.chat_json", side_effect=resume_script), \
             patch("baton.events.emit") as emit:
            self.runtime.run_bot(self.bot.name, resume_run=run, inbound_message=msg.name,
                                 inbound_channel="WhatsApp", inbound_from_assignee=True,
                                 run_reason="reply")

        self.lead.reload()
        self.assertEqual(self.lead.status, "Junk")
        disqualified = [c for c in emit.call_args_list if c.args[:1] == ("lead.disqualified",)]
        self.assertTrue(disqualified, "lead.disqualified was not emitted")
        self.assertEqual(disqualified[0].kwargs.get("reference_name"), self.lead.name)
