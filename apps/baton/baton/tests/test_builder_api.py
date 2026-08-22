"""Builder API tests.

The canvas posts a subset of what a node actually holds, and save_workflow
clears and rebuilds the nodes table. Anything the builder does not know about
therefore has to be carried across deliberately -- these tests are what stop
that regressing.
"""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from baton.api.workflow import get_workflow, save_workflow, test_run

from .test_engine import _delete_test_workflows, _node, _workflow


def _canvas_payload(wf_name):
    """What the builder posts: get_workflow's shape, minus the fields it drops."""
    wf = get_workflow(wf_name)
    for n in wf["nodes"]:
        for invisible in ("max_retries", "retry_delay", "on_error", "fallback_node"):
            n.pop(invisible, None)
    return wf


class TestLosslessSave(FrappeTestCase):
    def tearDown(self):
        _delete_test_workflows("T Api")

    def test_retry_policy_survives_a_canvas_save(self):
        """Retry/error policy is editable in Desk but invisible on the canvas."""
        wf = _workflow("T Api Retry", [
            _node("t", "Trigger", next_node="w"),
            _node("w", "Webhook", config={"url": "https://example.invalid"},
                  max_retries=3, retry_delay=45, on_error="Continue"),
        ])

        save_workflow(json.dumps(_canvas_payload(wf.name)))

        node = frappe.get_doc("Baton Workflow", wf.name).nodes[1]
        self.assertEqual(node.max_retries, 3)
        self.assertEqual(node.retry_delay, 45)
        self.assertEqual(node.on_error, "Continue")

    def test_trigger_event_name_round_trips(self):
        """The builder must be able to read and write what an Event workflow subscribes to.

        Not a data-loss fix: save_workflow loads the stored doc and never wrote
        this field, so it survived untouched. But get_workflow never returned it
        either, so the canvas could not show or change it.
        """
        wf = _workflow("T Api Event", [_node("t", "Trigger")],
                       trigger_type="Event", trigger_event_name="lead.replied")

        save_workflow(json.dumps(_canvas_payload(wf.name)))

        self.assertEqual(
            frappe.db.get_value("Baton Workflow", wf.name, "trigger_event_name"),
            "lead.replied",
        )

    def test_posted_value_wins_over_stored(self):
        """Carrying values across must not make them uneditable."""
        wf = _workflow("T Api Override", [
            _node("t", "Trigger", next_node="w"),
            _node("w", "Webhook", config={"url": "https://example.invalid"}, max_retries=3),
        ])

        payload = get_workflow(wf.name)
        payload["nodes"][1]["max_retries"] = 7
        save_workflow(json.dumps(payload))

        self.assertEqual(frappe.get_doc("Baton Workflow", wf.name).nodes[1].max_retries, 7)

    def test_zero_is_a_real_value_not_a_missing_one(self):
        """max_retries=0 is meaningful; it must not fall back to the stored 3."""
        wf = _workflow("T Api Zero", [
            _node("t", "Trigger", next_node="w"),
            _node("w", "Webhook", config={"url": "https://example.invalid"}, max_retries=3),
        ])

        payload = get_workflow(wf.name)
        payload["nodes"][1]["max_retries"] = 0
        save_workflow(json.dumps(payload))

        self.assertEqual(frappe.get_doc("Baton Workflow", wf.name).nodes[1].max_retries, 0)


class TestTestRun(FrappeTestCase):
    def tearDown(self):
        _delete_test_workflows("T Api Test")

    def test_test_run_leaves_a_disabled_workflow_disabled(self):
        """It used to flip enabled=1 and restore in a finally.

        A worker killed between those two commits left the workflow permanently
        live and messaging real customers.
        """
        wf = _workflow("T Api Test Enabled", [_node("t", "Trigger")], enabled=0)

        result = test_run(wf.name)

        self.assertTrue(result["ok"])
        self.assertEqual(frappe.db.get_value("Baton Workflow", wf.name, "enabled"), 0)


class TestRunDetail(FrappeTestCase):
    """A run has to explain itself, including the things it refused to do."""

    def setUp(self):
        from .test_handoff import _settings, _snapshot_settings

        self._saved = _snapshot_settings()
        # ai_enabled off is the simplest reproducible refusal.
        _settings(ai_enabled=0)

    def tearDown(self):
        from .test_handoff import _settings

        _settings(**self._saved)
        _delete_test_workflows("T Detail")

    def _run_a_blocked_send(self):
        from baton.workflow.engine import run_workflow

        from .test_engine import _lead

        lead = _lead()
        wf = _workflow("T Detail Blocked", [
            _node("t", "Trigger", next_node="send"),
            _node("send", "Send WhatsApp",
                  config={"message": "Hi there", "author": "ai"}),
        ])
        return run_workflow(wf.name, doc=lead)

    def test_a_refused_send_is_not_recorded_as_a_success(self):
        from baton.api.workflow import get_run

        detail = get_run(self._run_a_blocked_send())
        send = next(s for s in detail["steps"] if s["node_id"] == "send")
        self.assertEqual(send["status"], "Skipped")

    def test_the_reason_it_refused_is_retrievable(self):
        """This is the question the product exists to answer."""
        from baton.api.workflow import get_run

        detail = get_run(self._run_a_blocked_send())
        suppressed = [l for l in detail["log"] if l["decision"] == "SUPPRESSED"]
        self.assertTrue(suppressed, "no audit row explains the refusal")
        self.assertIn("switched off", suppressed[0]["reason"])
        self.assertEqual(suppressed[0]["node_id"], "send")

    def test_a_waiting_run_says_what_it_is_waiting_for(self):
        from baton.api.workflow import get_run
        from baton.workflow.engine import run_workflow

        from .test_engine import _lead

        lead = _lead()
        wf = _workflow("T Detail Waiting", [
            _node("t", "Trigger", next_node="w"),
            _node("w", "Await Reply", config={"channel": "WhatsApp"},
                  next_node="a", next_node_alt="a"),
            _node("a", "Update Field", config={"field": "status", "value": "Contacted"}),
        ])
        detail = get_run(run_workflow(wf.name, doc=lead))
        self.assertEqual(detail["status"], "Waiting")
        self.assertEqual(detail["waiting_for"], "Reply")
        self.assertIsNotNone(detail["resume_at"])
