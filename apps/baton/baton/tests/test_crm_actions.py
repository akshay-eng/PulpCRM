"""The CRM-shaped steps, and the guards that stop them acting on the wrong thing.

The palette now talks about leads, deals, contacts and organizations rather than
about "Update Record". That helpfulness has a trap in it: the engine acts on
whichever record triggered the run, so a step written for a deal, dropped into a
lead workflow, would happily write to the lead. These tests pin the refusal.
"""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from baton.api.workflow import get_fields, validate_workflow
from baton.workflow.engine import run_workflow

from .test_engine import _delete_test_workflows, _lead, _node, _workflow


def _delete_converted():
    """Converting a lead makes a Deal, a Contact and an Organization, and the
    engine commits -- so FrappeTestCase's rollback cannot take them back.

    Leaving them behind is not merely untidy. CRM files a WhatsApp message
    against whichever record owns the phone number and prefers a Deal, so a
    stray converted deal on the shared test number silently re-homes another
    test's messages. That is exactly how the reference bug in
    overrides.whatsapp_message was found.
    """
    for deal in frappe.get_all("CRM Deal",
                               filters={"mobile_no": ["like", "+91999900%"]},
                               pluck="name"):
        frappe.delete_doc("CRM Deal", deal, force=True, ignore_permissions=True)
    for contact in frappe.get_all("Contact", filters={"first_name": "Engine"},
                                  pluck="name"):
        frappe.delete_doc("Contact", contact, force=True, ignore_permissions=True)
    frappe.db.commit()


def _last_step(run_name):
    doc = frappe.get_doc("Baton Workflow Run", run_name)
    return doc.steps[-1]


class TestRecordScope(FrappeTestCase):
    def tearDown(self):
        _delete_test_workflows("T Scope")

    def test_a_step_written_for_another_record_type_refuses_to_write(self):
        lead = _lead()
        wf = _workflow("T Scope Wrong", [
            _node("t", "Trigger", next_node="u"),
            _node("u", "Update Field",
                  config={"for_doctype": "CRM Deal", "field": "status",
                          "value": "Negotiation"}),
        ])
        before = frappe.db.get_value("CRM Lead", lead.name, "status")
        run = run_workflow(wf.name, doc=lead)

        self.assertEqual(frappe.db.get_value("CRM Lead", lead.name, "status"), before)
        self.assertIn("written for a CRM Deal", _last_step(run).output)

    def test_a_matching_step_still_writes(self):
        lead = _lead()
        wf = _workflow("T Scope Right", [
            _node("t", "Trigger", next_node="u"),
            _node("u", "Update Field",
                  config={"for_doctype": "CRM Lead", "field": "status",
                          "value": "Contacted"}),
        ])
        run_workflow(wf.name, doc=lead)
        self.assertEqual(
            frappe.db.get_value("CRM Lead", lead.name, "status"), "Contacted")

    def test_a_misspelt_field_is_reported_rather_than_silently_ignored(self):
        """`db.set_value` on a field that does not exist writes nothing and says
        nothing. That is the quietest way for an automation to be broken."""
        lead = _lead()
        wf = _workflow("T Scope Typo", [
            _node("t", "Trigger", next_node="u"),
            _node("u", "Update Field", config={"field": "staus", "value": "New"}),
        ])
        run = run_workflow(wf.name, doc=lead)
        self.assertIn("has no field", _last_step(run).output)

    def test_the_builder_warns_about_a_mismatched_step(self):
        problems = validate_workflow(json.dumps({
            "nodes": [
                {"node_id": "t", "node_type": "Trigger", "next_node": "u"},
                {"node_id": "u", "node_type": "Update Field",
                 "config": {"for_doctype": "CRM Deal", "field": "status"}},
            ],
            "triggers": [{"trigger_type": "Document Event", "trigger_doctype": "CRM Lead",
                          "trigger_event": "after_insert"}],
        }))
        self.assertTrue(any("written for a CRM Deal" in p["message"] for p in problems))


class TestCrmSteps(FrappeTestCase):
    def tearDown(self):
        _delete_test_workflows("T Crm")
        _delete_converted()

    def test_assigning_puts_it_on_someones_list(self):
        lead = _lead()
        wf = _workflow("T Crm Assign", [
            _node("t", "Trigger", next_node="a"),
            _node("a", "Assign To", config={"assign_to": "Administrator",
                                            "description": "Have a look"}),
        ])
        run_workflow(wf.name, doc=lead)
        self.assertTrue(frappe.db.exists("ToDo", {
            "reference_type": "CRM Lead", "reference_name": lead.name,
            "allocated_to": "Administrator", "status": "Open"}))

    def test_assigning_twice_is_quiet_rather_than_an_error(self):
        """Re-running a workflow should converge on the state it describes."""
        lead = _lead()
        wf = _workflow("T Crm Assign2", [
            _node("t", "Trigger", next_node="a"),
            _node("a", "Assign To", config={"assign_to": "Administrator"}),
        ])
        run_workflow(wf.name, doc=lead)
        run = run_workflow(wf.name, doc=lead)
        self.assertEqual(_last_step(run).status, "Skipped")

    def test_a_comment_lands_on_the_record(self):
        lead = _lead()
        wf = _workflow("T Crm Comment", [
            _node("t", "Trigger", next_node="c"),
            _node("c", "Add Comment",
                  config={"comment": "Auto-qualified from {{ doc.lead_name }}"}),
        ])
        run_workflow(wf.name, doc=lead)
        comments = frappe.get_all("Comment", filters={
            "reference_doctype": "CRM Lead", "reference_name": lead.name,
            "comment_type": "Comment"}, pluck="content")
        self.assertTrue(any("Engine Test" in (c or "") for c in comments))

    def test_a_note_lands_on_the_record(self):
        lead = _lead()
        wf = _workflow("T Crm Note", [
            _node("t", "Trigger", next_node="n"),
            _node("n", "Create Note", config={"title": "Auto", "content": "Wrote this."}),
        ])
        run_workflow(wf.name, doc=lead)
        self.assertTrue(frappe.db.exists("FCRM Note", {
            "reference_doctype": "CRM Lead", "reference_docname": lead.name}))

    def test_converting_a_lead_makes_a_deal(self):
        lead = _lead(email_id="convert@example.com")
        wf = _workflow("T Crm Convert", [
            _node("t", "Trigger", next_node="c"),
            _node("c", "Convert Lead"),
        ])
        run = run_workflow(wf.name, doc=lead)
        deal = json.loads(_last_step(run).output).get("deal")
        self.assertTrue(deal and frappe.db.exists("CRM Deal", deal))
        self.assertTrue(frappe.db.get_value("CRM Lead", lead.name, "converted"))

    def test_converting_something_that_is_not_a_lead_takes_the_other_branch(self):
        lead = _lead()
        wf = _workflow("T Crm ConvertTwice", [
            _node("t", "Trigger", next_node="c"),
            _node("c", "Convert Lead", next_node="ok", next_node_alt="no"),
            _node("ok", "Update Field", config={"field": "status", "value": "Qualified"}),
            _node("no", "Update Field", config={"field": "status", "value": "Junk"}),
        ])
        frappe.db.set_value("CRM Lead", lead.name, "converted", 1)
        lead.reload()
        run = run_workflow(wf.name, doc=lead)
        self.assertIn("already converted", frappe.get_doc(
            "Baton Workflow Run", run).steps[1].output)


class TestFieldCatalogue(FrappeTestCase):
    """What the pickers are allowed to offer."""

    def test_link_fields_carry_their_choices(self):
        """In Frappe CRM `status` is a Link, not a Select. Offering options only
        for Selects left the most-edited field in the product as free text."""
        fields = {f["field"]: f for f in get_fields("CRM Lead")}
        self.assertIn("status", fields)
        self.assertTrue(fields["status"]["options"],
                        "status must offer its allowed values")

    def test_a_doctype_outside_the_builder_returns_nothing(self):
        self.assertEqual(get_fields("User"), [])

    def test_a_huge_link_target_is_not_enumerated(self):
        """Listing every row of a big table into a dropdown is not a picker."""
        from baton.api.workflow import LINK_OPTION_LIMIT, _link_values

        self.assertLessEqual(len(_link_values("User")), LINK_OPTION_LIMIT)
