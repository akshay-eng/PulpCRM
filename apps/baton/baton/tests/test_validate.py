"""Graph validation.

MAX_STEPS catches a loop only after a hundred nodes' worth of side effects have
already happened. Anything visible in the graph is caught before it can be saved.
"""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from baton.api.workflow import save_workflow
from baton.workflow.validate import errors_only, validate_graph

from .test_engine import _delete_test_workflows


def _n(node_id, node_type="Update Field", **kw):
    node = {"node_id": node_id, "node_type": node_type,
            "config": {"field": "status", "value": "Contacted"}}
    node.update(kw)
    return node


def _messages(issues, level=None):
    return [i["message"] for i in issues if level is None or i["level"] == level]


class TestValidateGraph(FrappeTestCase):
    def test_empty_graph_is_an_error(self):
        self.assertTrue(errors_only(validate_graph([])))

    def test_duplicate_node_id(self):
        issues = validate_graph([_n("t", "Trigger", next_node="a"), _n("a"), _n("a")])
        self.assertIn("Duplicate node id 'a'.", _messages(issues, "error"))

    def test_dangling_branch(self):
        issues = validate_graph([_n("t", "Trigger", next_node="nowhere")])
        self.assertTrue(any("does not exist" in m for m in _messages(issues, "error")))

    def test_missing_required_config(self):
        issues = validate_graph([
            _n("t", "Trigger", next_node="s"),
            {"node_id": "s", "node_type": "Send WhatsApp", "config": {}},
        ])
        self.assertTrue(any("needs 'message'" in m for m in _messages(issues, "error")))

    def test_a_condition_needs_rules_or_an_expression(self):
        """Either route satisfies it; the picker replaced the mandatory code field."""
        issues = validate_graph([
            _n("t", "Trigger", next_node="c"),
            {"node_id": "c", "node_type": "Condition", "config": {}},
        ])
        self.assertTrue(any("Add a rule" in m for m in _messages(issues, "error")))

    def test_cycle_is_rejected(self):
        issues = validate_graph([
            _n("t", "Trigger", next_node="a"),
            _n("a", next_node="b"),
            _n("b", next_node="a"),
        ])
        self.assertTrue(any("loops back" in m for m in _messages(issues, "error")))

    def test_a_long_chain_is_not_mistaken_for_a_cycle(self):
        nodes = [_n("t", "Trigger", next_node="n0")]
        nodes += [_n(f"n{i}", next_node=f"n{i + 1}") for i in range(20)]
        nodes.append(_n("n20"))
        self.assertEqual(errors_only(validate_graph(nodes)), [])

    def test_a_diamond_is_not_a_cycle(self):
        """Two branches rejoining is normal, and must not read as a loop."""
        issues = validate_graph([
            _n("t", "Trigger", next_node="c"),
            {"node_id": "c", "node_type": "Condition", "config": {"expression": "True"},
             "next_node": "l", "next_node_alt": "r"},
            _n("l", next_node="end"),
            _n("r", next_node="end"),
            _n("end"),
        ])
        self.assertEqual(errors_only(issues), [])

    def test_unreachable_node_is_only_a_warning(self):
        issues = validate_graph([_n("t", "Trigger", next_node="a"), _n("a"), _n("orphan")])
        self.assertEqual(errors_only(issues), [])
        self.assertTrue(any("Nothing leads to" in m for m in _messages(issues, "warning")))

    def test_parking_node_without_a_timeout_branch_warns(self):
        issues = validate_graph([
            _n("t", "Trigger", next_node="w"),
            {"node_id": "w", "node_type": "Await Reply", "config": {}, "next_node": "a"},
            _n("a"),
        ])
        self.assertEqual(errors_only(issues), [])
        self.assertTrue(any("No timeout branch" in m for m in _messages(issues, "warning")))


class TestSaveRejectsBrokenGraphs(FrappeTestCase):
    def tearDown(self):
        _delete_test_workflows("T Val")

    def test_a_cycle_cannot_be_saved(self):
        payload = {
            "workflow_name": "T Val Cycle",
            "trigger_type": "Manual",
            "nodes": [
                _n("t", "Trigger", next_node="a"),
                _n("a", next_node="b"),
                _n("b", next_node="a"),
            ],
        }
        with self.assertRaises(frappe.ValidationError):
            save_workflow(json.dumps(payload))

    def test_warnings_do_not_block_a_save(self):
        """A half-wired graph is a normal state to be in while building one."""
        payload = {
            "workflow_name": "T Val Warn",
            "trigger_type": "Manual",
            "nodes": [_n("t", "Trigger", next_node="a"), _n("a"), _n("orphan")],
        }
        saved = save_workflow(json.dumps(payload))
        self.assertEqual(saved["workflow_name"], "T Val Warn")
