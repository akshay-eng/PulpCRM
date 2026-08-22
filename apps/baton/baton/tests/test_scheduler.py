"""Scheduler tests.

`test_engine.py` covers resumption by calling `run_workflow(resume_run=...)`
directly, which skips the scheduler entirely -- so the path that actually wakes
a parked run in production had no coverage at all. These tests drive
`resume_due_runs` itself.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from baton.workflow import scheduler
from baton.workflow.engine import run_workflow

from .test_engine import _delete_test_workflows, _lead, _node, _workflow


def _parked_run(name="T Sched Wait"):
    """A workflow parked on a Wait node, with its resume time already past."""
    lead = _lead()
    _workflow(name, [
        _node("t", "Trigger", next_node="w"),
        _node("w", "Wait", config={"amount": 1, "unit": "minutes"}, next_node="after"),
        _node("after", "Update Field", config={"field": "status", "value": "Contacted"}),
    ])
    run_name = run_workflow(name, doc=lead)
    frappe.db.set_value("Baton Workflow Run", run_name, "resume_at",
                        add_to_date(now_datetime(), seconds=-10))
    frappe.db.commit()
    return run_name, lead


class TestResumeDueRuns(FrappeTestCase):
    def tearDown(self):
        _delete_test_workflows("T Sched")

    def test_due_run_is_enqueued(self):
        """The whole point of the scheduler: a due run must actually be picked up.

        Regression -- `frappe.db.sql` returns () for every UPDATE (it has no
        cursor description), so the old `if not updated: continue` claim check
        was always true and every parked run was flipped to Running and then
        silently dropped.
        """
        run_name, _ = _parked_run()

        with patch("frappe.enqueue") as enq:
            scheduler.resume_due_runs()

        self.assertEqual(enq.call_count, 1, "a due run was never enqueued")
        kwargs = enq.call_args.kwargs
        self.assertEqual(kwargs["resume_run"], run_name)

    def test_due_run_is_not_stranded(self):
        """A run must never be left Running with nothing scheduled to continue it."""
        run_name, _ = _parked_run("T Sched Strand")

        with patch("frappe.enqueue") as enq:
            scheduler.resume_due_runs()

        status = frappe.db.get_value("Baton Workflow Run", run_name, "status")
        if not enq.call_count:
            self.assertNotEqual(
                status, "Running",
                "run was claimed but never enqueued -- it is a permanent zombie",
            )

    def test_overlapping_ticks_claim_a_run_only_once(self):
        """Two ticks racing must not resume the same run twice."""
        run_name, _ = _parked_run("T Sched Race")

        with patch("frappe.enqueue") as enq:
            scheduler.resume_due_runs()
            scheduler.resume_due_runs()

        self.assertEqual(enq.call_count, 1, "the same run was enqueued twice")

    def test_run_that_is_not_due_is_left_alone(self):
        run_name, _ = _parked_run("T Sched Future")
        frappe.db.set_value("Baton Workflow Run", run_name, "resume_at",
                            add_to_date(now_datetime(), hours=2))
        frappe.db.commit()

        with patch("frappe.enqueue") as enq:
            scheduler.resume_due_runs()

        self.assertEqual(enq.call_count, 0)
        self.assertEqual(
            frappe.db.get_value("Baton Workflow Run", run_name, "status"), "Waiting")
