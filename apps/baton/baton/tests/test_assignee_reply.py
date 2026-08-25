"""Asking the assigned rep something, and waking on their reply
specifically -- not the record's own contact.

The scenario these protect: a run parked on the assignee must be found by
the assignee's phone number regardless of what CRM reference the inbound
message resolves to (usually none), must never be woken by an unrelated
reply, and must survive both directions of cancellation that already apply
to a customer's own conversation on the same record.
"""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from baton.conversation.parking import resume_waiting_assignee
from baton.conversation.state import cancel_pending_ai_actions, mark_human_intervention

from .test_bot_runtime import _bot, _cleanup
from .test_engine import _lead


def _parked_run(bot, lead, number, waiting_since=None):
    run = frappe.get_doc({
        "doctype": "Baton Workflow Run", "bot": bot.name, "status": "Waiting",
        "waiting_for": "Reply", "waiting_channel": "WhatsApp",
        "waiting_from_number": number,
        "waiting_since": waiting_since or now_datetime(),
        "resume_node": "__bot__",
        "reference_doctype": "CRM Lead", "reference_name": lead.name,
        "context": json.dumps({"observations": [], "vars": {}, "turn": 0, "steps_used": 0}),
    }).insert(ignore_permissions=True)
    frappe.db.commit()
    return run


def _inbound(text="Went well, they want a proposal"):
    msg = frappe.get_doc({
        "doctype": "WhatsApp Message", "type": "Incoming", "to": "911234500000",
        "message": text, "content_type": "text", "baton_author": "contact",
    }).insert(ignore_permissions=True)
    frappe.db.commit()
    return msg


class TestResumeWaitingAssignee(FrappeTestCase):
    def setUp(self):
        self.lead = _lead()
        self.bot = _bot(connectors=("crm_leads", "whatsapp"))

    def tearDown(self):
        _cleanup()

    def test_a_reply_from_the_assignees_number_resumes_the_run(self):
        run = _parked_run(self.bot, self.lead, "+919000000004")
        msg = _inbound()

        with patch("frappe.enqueue") as enq:
            woken = resume_waiting_assignee("+919000000004", "WhatsApp", msg.name)

        self.assertEqual(woken, run.name)
        enq.assert_called_once()
        self.assertEqual(enq.call_args.kwargs["resume_run"], run.name)
        self.assertTrue(enq.call_args.kwargs["inbound_from_assignee"])
        self.assertEqual(enq.call_args.kwargs["inbound_message"], msg.name)

    def test_an_unrelated_number_does_not_resume_it(self):
        _parked_run(self.bot, self.lead, "+919000000004")
        msg = _inbound()

        with patch("frappe.enqueue") as enq:
            woken = resume_waiting_assignee("+919999999999", "WhatsApp", msg.name)

        self.assertIsNone(woken)
        enq.assert_not_called()

    def test_a_stale_message_is_ignored(self):
        """A webhook redelivering an old message must not answer a new ask."""
        run = _parked_run(self.bot, self.lead, "+919000000004")
        msg = _inbound()
        frappe.db.set_value("WhatsApp Message", msg.name, "creation",
                            add_to_date(now_datetime(), hours=-2), update_modified=False)
        frappe.db.set_value("Baton Workflow Run", run.name, "waiting_since",
                            now_datetime(), update_modified=False)
        frappe.db.commit()

        self.assertIsNone(resume_waiting_assignee("+919000000004", "WhatsApp", msg.name))

    def test_two_runs_on_the_same_assignee_most_recent_wins(self):
        older = _parked_run(self.bot, self.lead, "+919000000004",
                            waiting_since=add_to_date(now_datetime(), hours=-2))
        newer = _parked_run(self.bot, self.lead, "+919000000004")
        msg = _inbound()

        with patch("frappe.enqueue") as enq:
            woken = resume_waiting_assignee("+919000000004", "WhatsApp", msg.name)

        self.assertEqual(woken, newer.name)
        self.assertEqual(enq.call_args.kwargs["resume_run"], newer.name)
        # The older run isn't touched -- still Waiting, free to time out on
        # its own schedule rather than being cancelled or double-resumed.
        self.assertEqual(
            frappe.db.get_value("Baton Workflow Run", older.name, "status"), "Waiting")

    def test_a_customers_own_reply_does_not_wake_a_run_parked_on_the_assignee(self):
        """Regression test for the _waiting_run exclusion: before this fix, a
        run parked on the assignee's number would still match
        resume_on_inbound's own query, since both point at the same
        reference_doctype/reference_name."""
        from baton.conversation.parking import resume_on_inbound

        _parked_run(self.bot, self.lead, "+919000000004")
        msg = frappe.get_doc({
            "doctype": "WhatsApp Message", "type": "Incoming", "to": self.lead.mobile_no,
            "message": "hello", "content_type": "text", "baton_author": "contact",
            "reference_doctype": "CRM Lead", "reference_name": self.lead.name,
        }).insert(ignore_permissions=True)

        self.assertIsNone(resume_on_inbound("CRM Lead", self.lead.name, "WhatsApp", msg.name))


class TestAssigneeWaitSurvivesCancellation(FrappeTestCase):
    """Both directions: a human taking over the lead's own thread, and the
    lead's own reply, must leave a rep-directed wait alone -- it's a
    different conversation happening on the same record."""

    def setUp(self):
        self.lead = _lead()
        self.bot = _bot(connectors=("crm_leads", "whatsapp"))

    def tearDown(self):
        _cleanup()

    def test_human_intervention_on_the_lead_does_not_cancel_it(self):
        run = _parked_run(self.bot, self.lead, "+919000000004")
        mark_human_intervention("CRM Lead", self.lead.name, reason="rep took over")
        self.assertEqual(
            frappe.db.get_value("Baton Workflow Run", run.name, "status"), "Waiting")

    def test_the_leads_own_reply_cleanup_does_not_cancel_it(self):
        run = _parked_run(self.bot, self.lead, "+919000000004")
        cancel_pending_ai_actions("CRM Lead", self.lead.name, include_reply_waits=False)
        self.assertEqual(
            frappe.db.get_value("Baton Workflow Run", run.name, "status"), "Waiting")
