"""Overriding crm.api.invite_by_email so a lapsed invitation doesn't
silently block re-inviting the same person forever.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from baton.overrides.crm_invitation import invite_by_email

EMAIL = "t-invite-override@example.com"


class TestOverrideIsRegistered(FrappeTestCase):
    def test_override_is_registered(self):
        overrides = frappe.get_hooks("override_whitelisted_methods") or {}
        target = overrides.get("crm.api.invite_by_email")
        self.assertTrue(target)
        self.assertIn("baton.overrides.crm_invitation.invite_by_email", target)


class TestExpiredInvitationDoesNotBlockAReinvite(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")

    def tearDown(self):
        for name in frappe.get_all("CRM Invitation", filters={"email": EMAIL}, pluck="name"):
            frappe.delete_doc("CRM Invitation", name, force=True, ignore_permissions=True)
        for name in frappe.get_all("User", filters={"email": EMAIL}, pluck="name"):
            frappe.delete_doc("User", name, force=True, ignore_permissions=True)
        frappe.db.commit()

    def _invitation(self, status):
        # before_insert forces status to Pending regardless of what's passed
        # in, the same way the real expire_invitations() cron only ever
        # reaches Expired via a save after insert -- so status has to be set
        # as a second step, not in the initial dict.
        doc = frappe.get_doc({
            "doctype": "CRM Invitation", "email": EMAIL, "role": "Sales User",
        }).insert(ignore_permissions=True)
        frappe.db.set_value("CRM Invitation", doc.name, "status", status)
        frappe.db.commit()
        return doc

    def test_an_expired_invitation_can_be_reinvited(self):
        self._invitation("Expired")
        result = invite_by_email(emails=EMAIL, role="Sales User")
        self.assertEqual(result["existing_invites"], [])
        self.assertEqual(result["to_invite"], [EMAIL])

    def test_a_rejected_invitation_can_be_reinvited(self):
        self._invitation("Rejected")
        result = invite_by_email(emails=EMAIL, role="Sales User")
        self.assertEqual(result["to_invite"], [EMAIL])

    def test_a_genuinely_pending_invitation_still_blocks_a_duplicate(self):
        """The fix must not turn into "always allow" -- a real pending
        invitation must still stop a second one going out."""
        self._invitation("Pending")
        result = invite_by_email(emails=EMAIL, role="Sales User")
        self.assertEqual(result["existing_invites"], [EMAIL])
        self.assertEqual(result["to_invite"], [])
