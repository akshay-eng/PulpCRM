from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from baton.api.chat import _clean_values, _validate, ask, execute_action, history


class TestChatWithoutQuery(FrappeTestCase):
	def test_null_doctype_is_a_valid_non_query_answer(self):
		self.assertEqual(
			_validate({"doctype": None, "explanation": "Hello!"}),
			(None, [], {}, None, 0),
		)

	def test_greeting_returns_an_answer_instead_of_validation_error(self):
		with patch(
			"baton.api.chat.chat_json",
			return_value={"doctype": None, "explanation": "Hi! Ask me about your CRM."},
		):
			result = ask("hi")

		self.assertEqual(result["answer"], "Hi! Ask me about your CRM.")
		self.assertIsNone(result["doctype"])
		self.assertEqual(result["rows"], [])


class TestChatActions(FrappeTestCase):
	def _lead(self, name="Ask Pulp Action"):
		return frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": "Ask",
				"last_name": "Pulp",
				"lead_name": name,
				"status": "New",
			}
		).insert(ignore_permissions=True)

	def test_update_is_previewed_before_it_changes_anything(self):
		lead = self._lead()
		with patch(
			"baton.api.chat.chat_json",
			return_value={
				"action": "update",
				"doctype": "CRM Lead",
				"filters": {"name": lead.name},
				"values": {"status": "Contacted"},
				"explanation": "Move this lead to Contacted.",
			},
		):
			result = ask("Mark this lead as contacted")

		self.assertEqual(frappe.db.get_value("CRM Lead", lead.name, "status"), "New")
		self.assertEqual(result["pending_action"]["status"], "pending")

		completed = execute_action(result["pending_action"]["id"])
		self.assertEqual(completed["status"], "completed")
		self.assertEqual(frappe.db.get_value("CRM Lead", lead.name, "status"), "Contacted")

		repeated = execute_action(result["pending_action"]["id"])
		self.assertEqual(repeated["status"], "completed")
		self.assertEqual(len(repeated["results"]), 1)

	def test_cancelled_update_changes_nothing(self):
		lead = self._lead("Ask Pulp Cancel")
		with patch(
			"baton.api.chat.chat_json",
			return_value={
				"action": "update",
				"doctype": "CRM Lead",
				"filters": {"name": lead.name},
				"values": {"status": "Contacted"},
			},
		):
			result = ask("Prepare an update")

		cancelled = execute_action(result["pending_action"]["id"], "cancel")
		self.assertEqual(cancelled["status"], "cancelled")
		self.assertEqual(frappe.db.get_value("CRM Lead", lead.name, "status"), "New")

	def test_export_reuses_a_validated_permission_aware_query(self):
		with patch(
			"baton.api.chat.chat_json",
			return_value={
				"action": "export",
				"doctype": "CRM Lead",
				"fields": ["name", "lead_name", "not_a_field"],
				"filters": {"status": "New"},
				"limit": 99999,
				"file_format": "CSV",
				"explanation": "Exporting new leads.",
			},
		):
			result = ask("Export new leads")

		self.assertEqual(result["export"]["doctype"], "CRM Lead")
		self.assertEqual(result["export"]["limit"], 5000)
		self.assertNotIn("not_a_field", result["export"]["fields"])

	def test_create_is_also_confirmed_before_insert(self):
		with patch(
			"baton.api.chat.chat_json",
			return_value={
				"action": "create",
				"doctype": "CRM Lead",
				"values": {
					"first_name": "Created",
					"last_name": "In Chat",
					"lead_name": "Created In Chat",
				},
			},
		):
			result = ask("Create a lead called Created In Chat")

		self.assertFalse(frappe.db.exists("CRM Lead", {"lead_name": "Created In Chat"}))
		completed = execute_action(result["pending_action"]["id"])
		self.assertEqual(completed["status"], "completed")
		self.assertTrue(frappe.db.exists("CRM Lead", {"lead_name": "Created In Chat"}))

	def test_follow_up_turn_receives_the_previous_query_targets(self):
		lead = self._lead("Ask Pulp Context")
		plans = [
			{
				"action": "query",
				"doctype": "CRM Lead",
				"fields": ["name", "lead_name"],
				"filters": {"name": lead.name},
			},
			{"action": "help", "doctype": None, "explanation": "I remember it."},
		]
		with patch("baton.api.chat.chat_json", side_effect=plans) as planner:
			first = ask("Show this lead")
			ask("What about that one?", session=first["session"])

		messages = planner.call_args_list[1].args[0]
		self.assertTrue(
			any(lead.name in message["content"] for message in messages),
			"the next turn must receive the previous query's record ids",
		)

	def test_unfiltered_updates_are_refused(self):
		with patch(
			"baton.api.chat.chat_json",
			return_value={
				"action": "update",
				"doctype": "CRM Lead",
				"filters": {},
				"values": {"status": "Contacted"},
			},
		):
			with self.assertRaises(frappe.ValidationError):
				ask("Update every lead")

	def test_structural_fields_cannot_be_changed(self):
		with self.assertRaises(frappe.ValidationError):
			_clean_values("CRM Lead", {"owner": "Administrator"})

	def test_invalid_filter_operator_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			_validate(
				{
					"doctype": "CRM Lead",
					"filters": {"status": ["exec", "New"]},
				}
			)

	def test_chat_history_is_private_to_its_owner(self):
		session = frappe.get_doc(
			{
				"doctype": "Baton Chat Session",
				"title": "Someone else's chat",
				"user": "Guest",
			}
		).insert(ignore_permissions=True)

		with self.assertRaises(frappe.PermissionError):
			history(session.name)
