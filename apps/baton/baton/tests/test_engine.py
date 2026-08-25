"""Workflow engine tests.

Covers the behaviours that are expensive to get wrong: sandboxed conditions,
branch selection, the cycle guard, durable waits, idempotency and retry.
"""

import json

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from baton.audit import already_done, log_action
from baton.workflow.engine import _eval, _wait_seconds, run_workflow


def _node(node_id, node_type, **kw):
    base = {"node_id": node_id, "node_type": node_type, "label": node_id}
    if "config" in kw:
        kw["config"] = json.dumps(kw["config"])
    base.update(kw)
    return base


def _workflow(name, nodes, **kw):
    if frappe.db.exists("Baton Workflow", name):
        frappe.delete_doc("Baton Workflow", name, force=True, ignore_permissions=True)
    doc = {
        "doctype": "Baton Workflow",
        "workflow_name": name,
        "enabled": 1,
        "trigger_type": "Manual",
        "nodes": nodes,
    }
    doc.update(kw)
    return frappe.get_doc(doc).insert(ignore_permissions=True)


def _lead(**kw):
    values = {
        "doctype": "CRM Lead",
        "first_name": "Engine",
        "last_name": "Test",
        "lead_name": "Engine Test",
        "mobile_no": "+919999000001",
    }
    values.update(kw)
    return frappe.get_doc(values).insert(ignore_permissions=True)



# Leads the fixtures create. The engine commits mid-test, so FrappeTestCase's
# rollback cannot remove them and they accumulate in the site on every run.
TEST_LEAD_NAMES = ("Engine Test", "Engine Renamed", "Handoff Test", "Qual Test")


def _delete_test_leads(*lead_names):
    """Remove leads these tests create, and everything hanging off them.

    The engine commits mid-test, so FrappeTestCase's rollback cannot take them
    back and they pile up in the real CRM. Called with no names it sweeps every
    fixture name this suite uses.
    """
    for lead_name in lead_names or TEST_LEAD_NAMES:
        for name in frappe.get_all("CRM Lead", filters={"lead_name": lead_name},
                                   pluck="name"):
            # Baton Approval matters as much as the lead itself: approvals are
            # committed while the lead insert is rolled back, so Frappe's naming
            # series rewinds and the next test's lead inherits the orphans. That
            # is what made cancel_pending_ai_actions count three of them.
            for child, field in (("WhatsApp Message", "reference_name"),
                                 ("Baton Conversation State", "reference_name"),
                                 ("Baton Qualification Result", "reference_name"),
                                 ("Baton Approval", "reference_name"),
                                 ("Baton Booking Hold", "reference_name")):
                if not frappe.db.exists("DocType", child):
                    continue
                for row in frappe.get_all(child, filters={field: name}, pluck="name"):
                    frappe.delete_doc(child, row, force=True, ignore_permissions=True)
            frappe.delete_doc("CRM Lead", name, force=True, ignore_permissions=True)

    # Anything left pointing at a lead that no longer exists.
    if frappe.db.exists("DocType", "Baton Approval"):
        for name, ref in frappe.get_all(
                "Baton Approval", filters={"reference_doctype": "CRM Lead"},
                fields=["name", "reference_name"], as_list=True):
            if ref and not frappe.db.exists("CRM Lead", ref):
                frappe.delete_doc("Baton Approval", name, force=True,
                                  ignore_permissions=True)
    frappe.db.commit()


def _delete_test_workflows(*prefixes):
    """The engine commits, so rollback cannot remove what tests created."""
    _delete_test_leads()
    for prefix in prefixes:
        for name in frappe.get_all("Baton Workflow",
                                   filters={"workflow_name": ["like", f"{prefix}%"]},
                                   pluck="name"):
            for run in frappe.get_all("Baton Workflow Run",
                                      filters={"workflow": name}, pluck="name"):
                frappe.delete_doc("Baton Workflow Run", run, force=True,
                                  ignore_permissions=True)
            frappe.delete_doc("Baton Workflow", name, force=True, ignore_permissions=True)
    frappe.db.commit()


class TestSafeEval(FrappeTestCase):
    def test_extended_builtins_available(self):
        """bool/len are not in Frappe's safe_eval whitelist; we add them."""
        lead = _lead()
        self.assertTrue(_eval("bool(doc.mobile_no)", lead))
        self.assertEqual(_eval("len(doc.lead_name)", lead), len("Engine Test"))

    def test_filesystem_access_is_blocked(self):
        """A workflow author must not be able to reach out of the sandbox."""
        lead = _lead()
        for hostile in ("__import__('os').system('echo pwned')",
                        "open('/etc/passwd').read()"):
            with self.assertRaises(Exception):
                _eval(hostile, lead)

    def test_payload_is_addressable(self):
        self.assertTrue(_eval("payload['ok']", None, {"ok": True}))


class TestBranching(FrappeTestCase):
    def test_true_branch_taken(self):
        lead = _lead(mobile_no="+919999000002")
        _workflow("T Branch True", [
            _node("t", "Trigger", next_node="c"),
            _node("c", "Condition", config={"expression": "bool(doc.mobile_no)"},
                  next_node="yes", next_node_alt="no"),
            _node("yes", "Update Field", config={"field": "status", "value": "Contacted"}),
            _node("no", "Update Field", config={"field": "status", "value": "Junk"}),
        ])
        run_workflow("T Branch True", doc=lead)
        lead.reload()
        self.assertEqual(lead.status, "Contacted")

    def test_false_branch_taken(self):
        lead = _lead(mobile_no=None)
        _workflow("T Branch False", [
            _node("t", "Trigger", next_node="c"),
            _node("c", "Condition", config={"expression": "bool(doc.mobile_no)"},
                  next_node="yes", next_node_alt="no"),
            _node("yes", "Update Field", config={"field": "status", "value": "Contacted"}),
            _node("no", "Update Field", config={"field": "status", "value": "Junk"}),
        ])
        run_workflow("T Branch False", doc=lead)
        lead.reload()
        self.assertEqual(lead.status, "Junk")


class TestCycleGuard(FrappeTestCase):
    def test_loop_is_stopped_and_marked_failed(self):
        """A graph that loops must terminate rather than spin forever."""
        lead = _lead()
        _workflow("T Loop", [
            _node("a", "Trigger", next_node="b"),
            _node("b", "Condition", config={"expression": "True"}, next_node="a"),
        ])
        run = frappe.get_doc("Baton Workflow Run", run_workflow("T Loop", doc=lead))
        self.assertEqual(run.status, "Failed")
        self.assertIn("loops", (run.error or ""))


class TestDurableWait(FrappeTestCase):
    def test_wait_persists_instead_of_blocking(self):
        """Spec §107: a wait must persist resume_at, not hold the worker."""
        lead = _lead()
        _workflow("T Wait", [
            _node("t", "Trigger", next_node="w"),
            _node("w", "Wait", config={"amount": 2, "unit": "days"}, next_node="after"),
            _node("after", "Update Field", config={"field": "status", "value": "Contacted"}),
        ])
        run = frappe.get_doc("Baton Workflow Run", run_workflow("T Wait", doc=lead))

        self.assertEqual(run.status, "Waiting")
        self.assertEqual(run.resume_node, "after")
        self.assertIsNotNone(run.resume_at)

        # The node after the wait must NOT have run yet.
        lead.reload()
        self.assertNotEqual(lead.status, "Contacted")

    def test_resume_continues_from_the_stored_node(self):
        lead = _lead()
        _workflow("T Wait Resume", [
            _node("t", "Trigger", next_node="w"),
            _node("w", "Wait", config={"amount": 1, "unit": "minutes"}, next_node="after"),
            _node("after", "Update Field", config={"field": "status", "value": "Contacted"}),
        ])
        run_name = run_workflow("T Wait Resume", doc=lead)

        # Pull the resume time into the past, as the scheduler would find it.
        frappe.db.set_value("Baton Workflow Run", run_name, "resume_at",
                            add_to_date(now_datetime(), seconds=-10))
        run_workflow("T Wait Resume", resume_run=run_name)

        lead.reload()
        self.assertEqual(lead.status, "Contacted")
        self.assertEqual(frappe.db.get_value("Baton Workflow Run", run_name, "status"), "Completed")

    def test_wait_units(self):
        self.assertEqual(_wait_seconds({"amount": 3, "unit": "minutes"}), 180)
        self.assertEqual(_wait_seconds({"amount": 2, "unit": "hours"}), 7200)
        self.assertEqual(_wait_seconds({"amount": 1, "unit": "days"}), 86400)
        self.assertEqual(_wait_seconds({}), 1)  # never zero


class TestIdempotency(FrappeTestCase):
    def test_key_is_recorded_and_detected(self):
        key = f"test:{frappe.generate_hash(length=10)}"
        self.assertFalse(already_done(key))
        log_action("test.action", idempotency_key=key)
        self.assertTrue(already_done(key))

    def test_duplicate_key_cannot_be_inserted_twice(self):
        """The unique index is what actually prevents a double send."""
        key = f"test:{frappe.generate_hash(length=10)}"
        log_action("test.action", idempotency_key=key)
        frappe.db.commit()
        # Frappe wraps the MySQL 1062 as UniqueValidationError.
        with self.assertRaises(frappe.exceptions.UniqueValidationError):
            frappe.get_doc({
                "doctype": "Baton Action Log",
                "action": "test.action",
                "idempotency_key": key,
            }).insert(ignore_permissions=True)


class TestRetry(FrappeTestCase):
    def test_on_error_continue_proceeds_to_next_node(self):
        lead = _lead()
        _workflow("T Retry Continue", [
            _node("t", "Trigger", next_node="bad"),
            # A Create Document node with no doctype raises.
            _node("bad", "Create Document", config={}, next_node="after",
                  on_error="Continue", max_retries=0),
            _node("after", "Update Field", config={"field": "status", "value": "Contacted"}),
        ])
        run_workflow("T Retry Continue", doc=lead)
        lead.reload()
        self.assertEqual(lead.status, "Contacted")

    def test_on_error_fail_run_stops(self):
        lead = _lead()
        _workflow("T Retry Fail", [
            _node("t", "Trigger", next_node="bad"),
            _node("bad", "Create Document", config={}, next_node="after",
                  on_error="Fail run", max_retries=0),
            _node("after", "Update Field", config={"field": "status", "value": "Contacted"}),
        ])
        run = frappe.get_doc("Baton Workflow Run", run_workflow("T Retry Fail", doc=lead))
        self.assertEqual(run.status, "Failed")
        lead.reload()
        self.assertNotEqual(lead.status, "Contacted")


class TestAuditTrail(FrappeTestCase):
    def test_every_node_writes_an_action_log_row(self):
        lead = _lead()
        _workflow("T Audit", [
            _node("t", "Trigger", next_node="u"),
            _node("u", "Update Field", config={"field": "status", "value": "Contacted"}),
        ])
        run_name = run_workflow("T Audit", doc=lead)
        rows = frappe.get_all(
            "Baton Action Log",
            filters={"workflow_run": run_name, "action": ["like", "node.%"]},
            fields=["action", "node_id", "status"],
        )
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r.status == "Success" for r in rows))
        self.assertTrue(
            frappe.db.exists(
                "Baton Action Log",
                {
                    "workflow_run": run_name,
                    "action": "record.updated",
                    "reference_name": lead.name,
                },
            )
        )


def tearDownModule():
    _delete_test_leads('Engine Test')
    _delete_test_workflows('T ')
