"""Bots, inbound webhooks and run lifecycle events.

The webhook tests are the important ones: this is a guest-accessible endpoint
that starts CRM automations, so every way it can be talked into running
something it should not is worth pinning down.
"""

import hashlib
import hmac
import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from baton.api import trigger_webhook as hook
from baton.api.workflow import get_workflow, save_workflow
from baton.workflow.engine import run_workflow
from baton.workflow.validate import errors_only, validate_graph

from .test_engine import _delete_test_workflows, _lead, _node, _workflow


def _sign(body, secret):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _node_dict(node_id, node_type="Update Field", **kw):
    node = {"node_id": node_id, "node_type": node_type,
            "config": {"field": "status", "value": "Contacted"}}
    node.update(kw)
    return node


class TestWorkflowsMayPause(FrappeTestCase):
    """A workflow may wait wherever it likes.

    "Bot" used to mean "a workflow forbidden to pause", which was never a real
    distinction -- same runtime, same storage, smaller palette. A Bot is now its
    own thing entirely (see TestBotDefinition), and the restriction is gone.
    """

    def test_a_workflow_may_wait_for_a_reply(self):
        issues = validate_graph([
            _node_dict("t", "Trigger", next_node="w"),
            _node_dict("w", "Await Reply", next_node="a", next_node_alt="a"),
            _node_dict("a"),
        ])
        self.assertEqual(errors_only(issues), [])


class TestWebhookTrigger(FrappeTestCase):
    def setUp(self):
        wf = _workflow("T Hook Flow", [_node("t", "Trigger")], enabled=1)
        wf.append("triggers", {"enabled": 1, "trigger_type": "Webhook"})
        wf.save(ignore_permissions=True)
        frappe.db.commit()
        # save_workflow generates the path and secret together
        saved = save_workflow(json.dumps(get_workflow(wf.name)))
        self.wf_name = wf.name
        self.path = saved["triggers"][0]["webhook_path"]
        self.trigger = frappe.db.get_value(
            "Baton Workflow Trigger", {"webhook_path": self.path}, "name")
        self.secret = frappe.utils.password.get_decrypted_password(
            "Baton Workflow Trigger", self.trigger, "webhook_secret",
            raise_exception=False)

    def tearDown(self):
        _delete_test_workflows("T Hook")

    def _post(self, body, signature=None, path=None):
        """Drive receive() with a faked request, as the webhook layer sees it."""
        class _Req:
            def __init__(self, data):
                self._data = data

            def get_data(self):
                return self._data

        frappe.local.request = _Req(body)
        headers = {hook.SIGNATURE_HEADER: signature} if signature else {}
        with patch.object(frappe, "get_request_header",
                          side_effect=lambda k, *a: headers.get(k)):
            return hook.receive(path=path or self.path)

    def test_a_signed_call_starts_the_workflow(self):
        body = json.dumps({"hello": "world"}).encode()
        with patch("frappe.enqueue") as enq:
            out = self._post(body, _sign(body, self.secret))
        self.assertTrue(out["ok"])
        self.assertEqual(enq.call_args.kwargs["workflow_name"], self.wf_name)

    def test_an_unsigned_call_is_refused(self):
        body = b'{"hello":"world"}'
        with patch("frappe.enqueue") as enq:
            out = self._post(body)
        self.assertFalse(out["ok"])
        self.assertEqual(enq.call_count, 0)

    def test_a_wrong_signature_is_refused(self):
        body = b'{"hello":"world"}'
        with patch("frappe.enqueue") as enq:
            out = self._post(body, _sign(body, "not-the-secret"))
        self.assertFalse(out["ok"])
        self.assertEqual(enq.call_count, 0)

    def test_a_tampered_body_is_refused(self):
        """The signature covers the body, so changing it must invalidate it."""
        body = b'{"amount":1}'
        signature = _sign(body, self.secret)
        with patch("frappe.enqueue") as enq:
            out = self._post(b'{"amount":9999}', signature)
        self.assertFalse(out["ok"])
        self.assertEqual(enq.call_count, 0)

    def test_no_secret_fails_closed(self):
        """An unconfigured trigger refuses everything rather than accepting anything."""
        # Password fields live in __Auth, so clearing the column is not enough --
        # get_decrypted_password would still hand back the old secret.
        frappe.utils.password.remove_encrypted_password(
            "Baton Workflow Trigger", self.trigger, "webhook_secret")
        frappe.db.set_value("Baton Workflow Trigger", self.trigger, "webhook_secret", "")
        frappe.db.commit()
        body = b"{}"
        with patch("frappe.enqueue") as enq:
            out = self._post(body, _sign(body, self.secret))
        self.assertFalse(out["ok"])
        self.assertEqual(enq.call_count, 0)

    def test_an_unknown_path_is_refused(self):
        body = b"{}"
        with patch("frappe.enqueue") as enq:
            out = self._post(body, _sign(body, self.secret), path="nope")
        self.assertFalse(out["ok"])
        self.assertEqual(enq.call_count, 0)

    def test_a_disabled_workflow_does_not_run(self):
        frappe.db.set_value("Baton Workflow", self.wf_name, "enabled", 0)
        frappe.db.commit()
        body = b"{}"
        with patch("frappe.enqueue") as enq:
            out = self._post(body, _sign(body, self.secret))
        self.assertFalse(out["ok"])
        self.assertEqual(enq.call_count, 0)

    def test_the_caller_cannot_point_the_run_at_any_doctype(self):
        """A signed third party still may not aim a workflow at the User table."""
        body = json.dumps({"reference_doctype": "User",
                           "reference_name": "Administrator"}).encode()
        with patch("frappe.enqueue") as enq:
            self._post(body, _sign(body, self.secret))
        self.assertIsNone(enq.call_args.kwargs["reference_doctype"])

    def test_a_crm_doctype_is_allowed_through(self):
        lead = _lead()
        body = json.dumps({"reference_doctype": "CRM Lead",
                           "reference_name": lead.name}).encode()
        with patch("frappe.enqueue") as enq:
            self._post(body, _sign(body, self.secret))
        self.assertEqual(enq.call_args.kwargs["reference_doctype"], "CRM Lead")


class TestLifecycleEvents(FrappeTestCase):
    def tearDown(self):
        _delete_test_workflows("T Life")

    def test_a_run_announces_that_it_started_and_finished(self):
        lead = _lead()
        wf = _workflow("T Life Flow", [
            _node("t", "Trigger", next_node="u"),
            _node("u", "Update Field", config={"field": "status", "value": "Contacted"}),
        ])
        run_workflow(wf.name, doc=lead)

        logged = frappe.get_all("Baton Action Log",
                                filters={"reference_name": lead.name,
                                         "action": ["like", "event.workflow.%"]},
                                pluck="action")
        self.assertIn("event.workflow.started", logged)
        self.assertIn("event.workflow.completed", logged)

    def test_nothing_can_subscribe_to_a_lifecycle_event(self):
        """A workflow triggering on its own completion is a loop between runs."""
        from baton.events import emit

        lead = _lead()
        wf = _workflow("T Life Sub", [_node("t", "Trigger")])
        wf.append("triggers", {"enabled": 1, "trigger_type": "Event",
                               "event_name": "workflow.completed"})
        wf.save(ignore_permissions=True)
        frappe.db.commit()

        with patch("frappe.enqueue") as enq:
            emit("workflow.completed", reference_doctype="CRM Lead",
                 reference_name=lead.name)
        self.assertEqual(enq.call_count, 0)
