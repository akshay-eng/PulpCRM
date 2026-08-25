import json

import frappe
from frappe.tests.utils import FrappeTestCase

from baton.api.audit import get_audit_trail
from baton.audit import AUDITED_DOCTYPES, _bounded_changes, audit_context


class TestAuditTrail(FrappeTestCase):
	def _lead(self, label="Pulp Audit"):
		return frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": "Pulp",
				"last_name": "Audit",
				"lead_name": label,
				"status": "New",
			}
		).insert(ignore_permissions=True)

	def test_every_user_facing_record_type_is_in_scope(self):
		self.assertTrue(
			{
				"CRM Lead",
				"CRM Deal",
				"Contact",
				"CRM Organization",
				"CRM Task",
				"FCRM Note",
				"CRM Call Log",
				"Baton Bot",
				"Baton Workflow",
			}.issubset(set(AUDITED_DOCTYPES))
		)

	def test_large_workflow_diffs_remain_valid_bounded_json(self):
		changes = [
			{"field": f"field_{index}", "label": f"Field {index}", "before": "x" * 2000, "after": "y" * 2000}
			for index in range(20)
		]
		packed = json.dumps({"changes": _bounded_changes(changes)})
		self.assertLess(len(packed), 8000)
		self.assertIn("Additional changes", packed)

	def test_update_captures_actor_source_reason_and_before_after(self):
		lead = self._lead()
		with audit_context(source="Ask Pulp", actor_type="HUMAN", reason="Qualified on the call"):
			lead.status = "Contacted"
			lead.save(ignore_permissions=True)

		row = frappe.get_all(
			"Baton Action Log",
			filters={"action": "record.updated", "reference_name": lead.name},
			fields=["actor_type", "actor_id", "input", "output", "reason"],
			order_by="creation desc",
			limit=1,
		)[0]
		changes = json.loads(row.input)["changes"]
		status = next(change for change in changes if change["field"] == "status")
		self.assertEqual((status["before"], status["after"]), ("New", "Contacted"))
		self.assertEqual(row.actor_type, "HUMAN")
		self.assertEqual(json.loads(row.output)["source"], "Ask Pulp")
		self.assertEqual(row.reason, "Qualified on the call")

	def test_api_returns_parsed_permission_checked_entries(self):
		lead = self._lead("Pulp Audit API")
		with audit_context(source="User interface", actor_type="HUMAN"):
			lead.status = "Contacted"
			lead.save(ignore_permissions=True)

		result = get_audit_trail("CRM Lead", lead.name)
		entry = next(item for item in result["entries"] if item["event"] == "updated")
		self.assertEqual(entry["reference_name"], lead.name)
		self.assertEqual(entry["source"], "User interface")
		self.assertIsInstance(entry["changes"], list)
