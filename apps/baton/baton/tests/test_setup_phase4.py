"""The round-robin Assignment Rule installers.

Both Deal and Lead versions share one implementation; the tests that matter
are that each targets the right document_type and that re-running is a
no-op rather than a duplicate-name error.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from baton import setup_phase4

DEAL_RULE = "Baton — Round robin Deals"
LEAD_RULE = "Baton — Round robin Leads"


class TestAssignmentRuleInstallers(FrappeTestCase):
    def tearDown(self):
        for name in (DEAL_RULE, LEAD_RULE):
            if frappe.db.exists("Assignment Rule", name):
                frappe.delete_doc("Assignment Rule", name, force=True, ignore_permissions=True)
        frappe.db.commit()

    def test_lead_rule_targets_crm_lead(self):
        setup_phase4.install_assignment_rule_lead()
        doc = frappe.get_doc("Assignment Rule", LEAD_RULE)
        self.assertEqual(doc.document_type, "CRM Lead")
        self.assertEqual(doc.rule, "Round Robin")
        self.assertFalse(doc.disabled)
        self.assertTrue(doc.users)

    def test_deal_rule_still_targets_crm_deal(self):
        setup_phase4.install_assignment_rule()
        doc = frappe.get_doc("Assignment Rule", DEAL_RULE)
        self.assertEqual(doc.document_type, "CRM Deal")

    def test_installing_twice_is_a_no_op(self):
        first = setup_phase4.install_assignment_rule_lead()
        second = setup_phase4.install_assignment_rule_lead()
        self.assertEqual(first, second)
        self.assertEqual(
            frappe.db.count("Assignment Rule", {"name": LEAD_RULE}), 1)
