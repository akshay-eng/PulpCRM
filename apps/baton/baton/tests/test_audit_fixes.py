"""Regressions found auditing the builder as a product rather than as code.

Each of these passed its unit tests and still failed a user. They are grouped
here because that is what they have in common.
"""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from baton.api.workflow import (
    get_fields,
    get_operators,
    get_workflow,
    save_workflow,
    test_run,
)
from baton.workflow.engine import _rules_to_expression

from .test_engine import _delete_test_workflows, _lead, _node, _workflow


class TestTheTestButton(FrappeTestCase):
    """It reported a green Completed while skipping everything that mattered."""

    def tearDown(self):
        _delete_test_workflows("T Audit")

    def _built_in_the_ui(self, name):
        return save_workflow(json.dumps({
            "workflow_name": name,
            "triggers": [{"enabled": 1, "trigger_type": "Document Event",
                          "trigger_doctype": "CRM Lead", "trigger_event": "after_insert"}],
            "nodes": [
                {"node_id": "t", "node_type": "Trigger", "next_node": "u"},
                {"node_id": "u", "node_type": "Update Field",
                 "config": {"field": "status", "value": "Contacted"}},
            ],
        }))

    def test_it_finds_a_record_from_the_triggers_table(self):
        """Triggers moved to a child table; this still read the old scalar field."""
        _lead()
        saved = self._built_in_the_ui("T Audit Test Button")
        result = test_run(saved["name"])

        step = next(s for s in result["run"]["steps"] if s["node_id"] == "u")
        self.assertEqual(step["status"], "Success",
                         "the test ran without a record, so nothing was exercised")

    def test_it_warns_rather_than_reporting_a_hollow_success(self):
        for name in frappe.get_all("CRM Lead", pluck="name"):
            frappe.delete_doc("CRM Lead", name, force=True, ignore_permissions=True)
        frappe.db.commit()

        saved = self._built_in_the_ui("T Audit Empty")
        result = test_run(saved["name"])
        self.assertTrue(result["warning"], "a test that ran against nothing looked like a pass")


class TestFallbackIsNotADeadEnd(FrappeTestCase):
    def tearDown(self):
        _delete_test_workflows("T Audit")

    def test_a_fallback_can_be_cleared_from_the_builder(self):
        """Deleting the fallback target used to make the graph unsaveable."""
        saved = save_workflow(json.dumps({
            "workflow_name": "T Audit Fallback",
            "nodes": [
                {"node_id": "t", "node_type": "Trigger", "next_node": "c"},
                {"node_id": "c", "node_type": "Webhook",
                 "config": {"url": "https://example.invalid"},
                 "on_error": "Go to fallback", "fallback_node": "rescue"},
                {"node_id": "rescue", "node_type": "Create Task",
                 "config": {"subject": "failed"}},
            ],
        }))
        self.assertEqual(saved["nodes"][1]["fallback_node"], "rescue")

        # What the canvas now posts after deleting the rescue node.
        payload = get_workflow(saved["name"])
        payload["nodes"] = [n for n in payload["nodes"] if n["node_id"] != "rescue"]
        for n in payload["nodes"]:
            if n.get("fallback_node") == "rescue":
                n["fallback_node"] = None
                n["on_error"] = "Fail run"

        again = save_workflow(json.dumps(payload))
        self.assertIsNone(again["nodes"][1]["fallback_node"])

    def test_error_handling_is_reachable_from_the_builder(self):
        from baton.api.workflow import ERROR_SCHEMA

        exposed = {f["field"] for f in ERROR_SCHEMA}
        self.assertEqual(
            exposed, {"on_error", "max_retries", "retry_delay", "fallback_node"},
            "retry and fallback exist on the doctype but cannot be set by a user")


class TestConditionsWithoutPython(FrappeTestCase):
    """The main branching primitive required writing a Python expression."""

    def test_rules_compile_to_an_expression(self):
        expr = _rules_to_expression([
            {"field": "status", "operator": "is", "value": "New"},
            {"field": "mobile_no", "operator": "is set"},
        ])
        self.assertIn("doc.status == 'New'", expr)
        self.assertIn("bool(doc.mobile_no)", expr)
        self.assertIn(" and ", expr)

    def test_every_offered_operator_is_implemented(self):
        """The UI must not be able to offer something the engine cannot evaluate."""
        for op in get_operators():
            expr = _rules_to_expression([{"field": "status", "operator": op, "value": "x"}])
            self.assertTrue(expr, f"operator {op!r} produced nothing")

    def test_a_crafted_field_name_cannot_inject(self):
        expr = _rules_to_expression([
            {"field": "status; import os", "operator": "is", "value": "New"},
        ])
        self.assertIsNone(expr)

    def test_a_value_is_always_a_literal(self):
        expr = _rules_to_expression([
            {"field": "status", "operator": "is", "value": "New' or doc.name == '"},
        ])
        self.assertNotIn("or doc.name ==", expr.replace(repr("New' or doc.name == '"), ""))

    def test_rules_actually_branch_a_run(self):
        from baton.workflow.engine import run_workflow

        lead = _lead(status="New")
        wf = _workflow("T Audit Rules", [
            _node("t", "Trigger", next_node="c"),
            _node("c", "Condition",
                  config={"rules": [{"field": "status", "operator": "is", "value": "New"}]},
                  next_node="yes", next_node_alt="no"),
            _node("yes", "Update Field", config={"field": "status", "value": "Contacted"}),
            _node("no", "Update Field", config={"field": "status", "value": "Junk"}),
        ])
        run_workflow(wf.name, doc=lead)
        lead.reload()
        self.assertEqual(lead.status, "Contacted")
        _delete_test_workflows("T Audit")

    def test_a_written_expression_still_wins(self):
        """The escape hatch has to keep working for people already using it."""
        from baton.workflow.engine import run_workflow

        lead = _lead(status="New")
        wf = _workflow("T Audit Expr", [
            _node("t", "Trigger", next_node="c"),
            _node("c", "Condition",
                  config={"expression": "False",
                          "rules": [{"field": "status", "operator": "is", "value": "New"}]},
                  next_node="yes", next_node_alt="no"),
            _node("yes", "Update Field", config={"field": "status", "value": "Contacted"}),
            _node("no", "Update Field", config={"field": "status", "value": "Junk"}),
        ])
        run_workflow(wf.name, doc=lead)
        lead.reload()
        self.assertEqual(lead.status, "Junk")
        _delete_test_workflows("T Audit")

    def test_the_field_picker_is_scoped_to_crm_doctypes(self):
        self.assertTrue(get_fields("CRM Lead"))
        self.assertEqual(get_fields("User"), [], "offered fields from outside the CRM")


class TestConditionValidation(FrappeTestCase):
    """The validator kept demanding the Python field the picker replaced."""

    def _issues(self, config):
        from baton.workflow.validate import validate_graph

        return validate_graph([
            {"node_id": "t", "node_type": "Trigger", "next_node": "c"},
            {"node_id": "c", "node_type": "Condition", "config": config,
             "next_node": "t", "next_node_alt": "t"},
        ])

    def _errors(self, config):
        from baton.workflow.validate import errors_only

        return [i["message"] for i in errors_only(self._issues(config))]

    def test_rules_alone_are_enough_to_save(self):
        errs = self._errors({"rules": [{"field": "status", "operator": "is", "value": "New"}]})
        self.assertEqual([e for e in errs if "If / Else" in e or "expression" in e], [])

    def test_an_expression_alone_is_enough_to_save(self):
        errs = self._errors({"expression": "doc.status == 'New'"})
        self.assertEqual([e for e in errs if "If / Else" in e or "expression" in e], [])

    def test_neither_is_an_error(self):
        self.assertTrue(any("Add a rule" in e for e in self._errors({})))

    def test_a_half_built_rule_is_caught(self):
        errs = self._errors({"rules": [{"field": "", "operator": "is", "value": "New"}]})
        self.assertTrue(any("incomplete" in e for e in errs))
