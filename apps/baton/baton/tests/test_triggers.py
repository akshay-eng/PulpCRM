"""Triggers, now that a workflow can have several of them.

handle_document_event had no test coverage before this file, which is how the
old single-trigger query survived unnoticed for so long.
"""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from baton.api.workflow import get_workflow, save_workflow
from baton.events import emit
from baton.workflow import scheduler

from .test_engine import _delete_test_workflows, _lead, _node, _workflow


def _with_triggers(name, triggers, nodes=None, enabled=1):
    wf = _workflow(name, nodes or [_node("t", "Trigger")], enabled=enabled)
    for t in triggers:
        wf.append("triggers", t)
    wf.save(ignore_permissions=True)
    frappe.db.commit()
    return wf


def _fired_for(enq, workflow_name):
    return [c for c in enq.call_args_list if c.kwargs.get("workflow_name") == workflow_name]


class TestDocumentEventTrigger(FrappeTestCase):
    def tearDown(self):
        _delete_test_workflows("T Trig")

    def test_it_fires_from_the_triggers_table(self):
        _with_triggers("T Trig Insert", [
            {"enabled": 1, "trigger_type": "Document Event",
             "trigger_doctype": "CRM Lead", "trigger_event": "after_insert"},
        ])
        with patch("frappe.enqueue") as enq:
            _lead()
        self.assertEqual(len(_fired_for(enq, "T Trig Insert")), 1)

    def test_a_disabled_workflow_does_not_fire(self):
        _with_triggers("T Trig Off", [
            {"enabled": 1, "trigger_type": "Document Event",
             "trigger_doctype": "CRM Lead", "trigger_event": "after_insert"},
        ], enabled=0)
        with patch("frappe.enqueue") as enq:
            _lead()
        self.assertEqual(_fired_for(enq, "T Trig Off"), [])

    def test_a_disabled_trigger_row_does_not_fire(self):
        _with_triggers("T Trig RowOff", [
            {"enabled": 0, "trigger_type": "Document Event",
             "trigger_doctype": "CRM Lead", "trigger_event": "after_insert"},
        ])
        with patch("frappe.enqueue") as enq:
            _lead()
        self.assertEqual(_fired_for(enq, "T Trig RowOff"), [])

    def test_two_triggers_on_one_workflow_both_work(self):
        """A bot has to answer several things at once -- the point of the table."""
        _with_triggers("T Trig Multi", [
            {"enabled": 1, "trigger_type": "Document Event",
             "trigger_doctype": "CRM Lead", "trigger_event": "after_insert"},
            {"enabled": 1, "trigger_type": "Document Event",
             "trigger_doctype": "CRM Lead", "trigger_event": "on_update"},
        ])
        with patch("frappe.enqueue") as enq:
            lead = _lead()
        self.assertEqual(len(_fired_for(enq, "T Trig Multi")), 1)

        with patch("frappe.enqueue") as enq:
            lead.status = "Contacted"
            lead.save(ignore_permissions=True)
        self.assertEqual(len(_fired_for(enq, "T Trig Multi")), 1)

    def test_field_changed_suppresses_unrelated_saves(self):
        """Without this, on_update fires on literally every save."""
        _with_triggers("T Trig Field", [
            {"enabled": 1, "trigger_type": "Document Event", "trigger_doctype": "CRM Lead",
             "trigger_event": "on_update", "field_changed": "status"},
        ])
        lead = _lead()

        with patch("frappe.enqueue") as enq:
            lead.last_name = "Renamed"
            lead.save(ignore_permissions=True)
        self.assertEqual(_fired_for(enq, "T Trig Field"), [],
                         "fired on a save that did not touch status")

        with patch("frappe.enqueue") as enq:
            lead.status = "Contacted"
            lead.save(ignore_permissions=True)
        self.assertEqual(len(_fired_for(enq, "T Trig Field")), 1)

    def test_a_trigger_condition_gates_it(self):
        _with_triggers("T Trig Cond", [
            {"enabled": 1, "trigger_type": "Document Event", "trigger_doctype": "CRM Lead",
             "trigger_event": "after_insert", "condition": "doc.status == 'Qualified'"},
        ])
        with patch("frappe.enqueue") as enq:
            _lead()
        self.assertEqual(_fired_for(enq, "T Trig Cond"), [])


class TestEventAndScheduleTriggers(FrappeTestCase):
    def tearDown(self):
        _delete_test_workflows("T Trig")

    def test_event_trigger_fires_from_the_table(self):
        _with_triggers("T Trig Event", [
            {"enabled": 1, "trigger_type": "Event", "event_name": "lead.replied"},
        ])
        lead = _lead()
        with patch("frappe.enqueue") as enq:
            emit("lead.replied", reference_doctype="CRM Lead", reference_name=lead.name)
        self.assertEqual(len(_fired_for(enq, "T Trig Event")), 1)

    def test_scheduled_trigger_fires_from_the_table(self):
        _with_triggers("T Trig Cron", [
            {"enabled": 1, "trigger_type": "Scheduled", "cron": "* * * * *"},
        ])
        with patch("frappe.enqueue") as enq:
            scheduler.tick()
        self.assertEqual(len(_fired_for(enq, "T Trig Cron")), 1)


class TestTriggerRoundTrip(FrappeTestCase):
    def tearDown(self):
        _delete_test_workflows("T Trig")

    def test_triggers_survive_a_canvas_save(self):
        wf = _with_triggers("T Trig Save", [
            {"enabled": 1, "trigger_type": "Document Event",
             "trigger_doctype": "CRM Deal", "trigger_event": "on_update"},
        ])
        save_workflow(json.dumps(get_workflow(wf.name)))

        reloaded = get_workflow(wf.name)
        self.assertEqual(len(reloaded["triggers"]), 1)
        self.assertEqual(reloaded["triggers"][0]["trigger_doctype"], "CRM Deal")

    def test_a_webhook_path_is_stable_across_saves(self):
        """It is an address someone configured elsewhere; regenerating it breaks them."""
        wf = _with_triggers("T Trig Hook", [
            {"enabled": 1, "trigger_type": "Webhook"},
        ])
        save_workflow(json.dumps(get_workflow(wf.name)))
        first = get_workflow(wf.name)["triggers"][0]["webhook_path"]
        self.assertTrue(first)

        save_workflow(json.dumps(get_workflow(wf.name)))
        self.assertEqual(get_workflow(wf.name)["triggers"][0]["webhook_path"], first)
