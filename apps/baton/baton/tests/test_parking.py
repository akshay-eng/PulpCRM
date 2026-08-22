"""Parking a run on something external, and waking it again.

The scenario these protect is the one the whole builder rests on: send a
message, stop, and carry on when the customer answers -- or give up cleanly
when they never do.
"""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from baton.conversation.parking import resolve_approval, resume_on_inbound
from baton.conversation.state import mark_human_intervention
from baton.workflow import scheduler
from baton.workflow.engine import run_workflow

from .test_engine import _delete_test_workflows, _lead, _node, _workflow


TEST_ACCOUNT = "Baton Test Account"


def _account():
    """A WhatsApp account for message fixtures.

    Deliberately not marked default: the dev site's own routing must not change
    just because the tests ran. Messages reference it explicitly instead.
    """
    if not frappe.db.exists("WhatsApp Account", TEST_ACCOUNT):
        frappe.get_doc({
            "doctype": "WhatsApp Account",
            "account_name": TEST_ACCOUNT,
            "phone_id": "test-phone-id",
            "business_id": "test-business-id",
            "url": "https://graph.facebook.invalid",
            "version": "v19.0",
            "is_default_incoming": 0,
            "is_default_outgoing": 0,
        }).insert(ignore_permissions=True)
        frappe.db.commit()
    return TEST_ACCOUNT


def _inbound(lead, text="yes please"):
    """A message from the contact, as the webhook would insert it."""
    return frappe.get_doc({
        "doctype": "WhatsApp Message",
        "type": "Incoming",
        "to": lead.mobile_no,
        "message": text,
        "content_type": "text",
        "whatsapp_account": _account(),
        "reference_doctype": "CRM Lead",
        "reference_name": lead.name,
        "baton_author": "contact",
    }).insert(ignore_permissions=True)


def _await_reply_workflow(name):
    return _workflow(name, [
        _node("t", "Trigger", next_node="ask"),
        _node("ask", "Await Reply", config={"channel": "WhatsApp", "timeout_hours": 24},
              next_node="got", next_node_alt="gaveup"),
        _node("got", "Update Field", config={"field": "status", "value": "Contacted"}),
        _node("gaveup", "Update Field", config={"field": "status", "value": "Junk"}),
    ])


class TestAwaitReply(FrappeTestCase):
    def tearDown(self):
        _delete_test_workflows("T Park")

    def test_it_parks_with_a_deadline(self):
        """A wait with no deadline is a run nobody ever hears about again."""
        lead = _lead()
        _await_reply_workflow("T Park Basic")
        run = frappe.get_doc("Baton Workflow Run", run_workflow("T Park Basic", doc=lead))

        self.assertEqual(run.status, "Waiting")
        self.assertEqual(run.waiting_for, "Reply")
        self.assertEqual(run.waiting_channel, "WhatsApp")
        self.assertIsNotNone(run.resume_at)
        self.assertIsNotNone(run.waiting_since)
        # It re-enters itself to read the reply, and has somewhere to go on timeout.
        self.assertEqual(run.resume_node, "ask")
        self.assertEqual(run.resume_node_alt, "gaveup")

    def test_a_reply_resumes_it(self):
        lead = _lead()
        _await_reply_workflow("T Park Reply")
        run_name = run_workflow("T Park Reply", doc=lead)

        # The after_insert hook does the waking, so watch the insert itself
        # rather than calling resume_on_inbound a second time.
        with patch("frappe.enqueue") as enq:
            _inbound(lead)

        resumes = [c for c in enq.call_args_list
                   if c.kwargs.get("resume_run") == run_name]
        self.assertEqual(len(resumes), 1, "the inbound hook did not resume the parked run")
        self.assertEqual(resumes[0].kwargs["resume_phase"], "reply")
        self.assertEqual(resumes[0].kwargs["resume_at_node"], "ask")

    def test_the_reply_branch_runs_and_the_text_is_readable(self):
        lead = _lead()
        _await_reply_workflow("T Park Branch")
        run_name = run_workflow("T Park Branch", doc=lead)
        msg = _inbound(lead, "yes please")

        run_workflow("T Park Branch", resume_run=run_name, resume_at_node="ask",
                     resume_phase="reply", inbound_message=msg.name)

        lead.reload()
        self.assertEqual(lead.status, "Contacted")
        run = frappe.get_doc("Baton Workflow Run", run_name)
        self.assertEqual(run.status, "Completed")
        self.assertEqual(json.loads(run.context)["last_reply"], "yes please")

    def test_a_message_older_than_the_park_is_ignored(self):
        """A webhook redelivering an old message must not answer a new question."""
        lead = _lead()
        _await_reply_workflow("T Park Stale")
        run_name = run_workflow("T Park Stale", doc=lead)

        msg = _inbound(lead)
        frappe.db.set_value("WhatsApp Message", msg.name, "creation",
                            add_to_date(now_datetime(), hours=-2), update_modified=False)
        frappe.db.set_value("Baton Workflow Run", run_name, "waiting_since",
                            now_datetime(), update_modified=False)
        frappe.db.commit()

        self.assertIsNone(resume_on_inbound("CRM Lead", lead.name, "WhatsApp", msg.name))

    def test_timeout_takes_the_alternate_branch(self):
        lead = _lead()
        _await_reply_workflow("T Park Timeout")
        run_name = run_workflow("T Park Timeout", doc=lead)

        frappe.db.set_value("Baton Workflow Run", run_name, "resume_at",
                            add_to_date(now_datetime(), seconds=-5))
        frappe.db.commit()

        with patch("frappe.enqueue") as enq:
            scheduler.resume_due_runs()

        self.assertEqual(enq.call_count, 1)
        self.assertEqual(enq.call_args.kwargs["resume_at_node"], "gaveup")

    def test_a_newer_park_supersedes_an_older_one(self):
        """Two agents parked on one conversation would talk over each other."""
        lead = _lead()
        _await_reply_workflow("T Park First")
        first = run_workflow("T Park First", doc=lead)
        _await_reply_workflow("T Park Second")
        second = run_workflow("T Park Second", doc=lead)

        self.assertEqual(frappe.db.get_value("Baton Workflow Run", first, "status"), "Cancelled")
        self.assertEqual(frappe.db.get_value("Baton Workflow Run", second, "status"), "Waiting")


class TestReplyDoesNotCancelItsOwnRun(FrappeTestCase):
    def tearDown(self):
        _delete_test_workflows("T Cancel")

    def test_inbound_spares_the_run_waiting_for_it(self):
        """on_message used to cancel every Waiting run -- including this one."""
        lead = _lead()
        _await_reply_workflow("T Cancel Spare")
        run_name = run_workflow("T Cancel Spare", doc=lead)

        _inbound(lead)  # fires on_message via after_insert

        self.assertNotEqual(
            frappe.db.get_value("Baton Workflow Run", run_name, "status"), "Cancelled",
            "the customer's reply cancelled the run that was waiting for it",
        )

    def test_a_human_taking_over_still_cancels_it(self):
        """The exemption must not weaken handoff: a rep stepping in wins."""
        lead = _lead()
        _await_reply_workflow("T Cancel Human")
        run_name = run_workflow("T Cancel Human", doc=lead)

        mark_human_intervention("CRM Lead", lead.name, reason="rep took over")

        self.assertEqual(
            frappe.db.get_value("Baton Workflow Run", run_name, "status"), "Cancelled")


class TestApprovalResume(FrappeTestCase):
    def tearDown(self):
        _delete_test_workflows("T Appr")

    def _workflow_with_approval(self, name):
        return _workflow(name, [
            _node("t", "Trigger", next_node="a"),
            _node("a", "Request Approval", config={"kind": "Other", "draft": "ok?"},
                  next_node="yes", next_node_alt="no"),
            _node("yes", "Update Field", config={"field": "status", "value": "Contacted"}),
            _node("no", "Update Field", config={"field": "status", "value": "Junk"}),
        ])

    def test_approval_parks_with_a_deadline(self):
        """It used to set Waiting with no resume_at, so nothing ever resumed it."""
        lead = _lead()
        self._workflow_with_approval("T Appr Park")
        run = frappe.get_doc("Baton Workflow Run", run_workflow("T Appr Park", doc=lead))

        self.assertEqual(run.status, "Waiting")
        self.assertEqual(run.waiting_for, "Approval")
        self.assertIsNotNone(run.resume_at)

    def test_approving_continues_down_the_normal_branch(self):
        lead = _lead()
        self._workflow_with_approval("T Appr Yes")
        run_name = run_workflow("T Appr Yes", doc=lead)
        approval = frappe.get_all("Baton Approval",
                                  filters={"workflow_run": run_name}, pluck="name")[0]

        with patch("frappe.enqueue") as enq:
            result = resolve_approval(approval, "Approved")

        self.assertTrue(result["ok"])
        self.assertEqual(enq.call_args.kwargs["resume_at_node"], "yes")

    def test_rejecting_takes_the_alternate_branch(self):
        lead = _lead()
        self._workflow_with_approval("T Appr No")
        run_name = run_workflow("T Appr No", doc=lead)
        approval = frappe.get_all("Baton Approval",
                                  filters={"workflow_run": run_name}, pluck="name")[0]

        with patch("frappe.enqueue") as enq:
            resolve_approval(approval, "Rejected")

        self.assertEqual(enq.call_args.kwargs["resume_at_node"], "no")
