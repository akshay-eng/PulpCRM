"""Email author tagging and human-intervention detection.

Mirrors the WhatsApp coverage in test_parking.py -- the whole point of
api/email_inbound.py is that a reply over email gets identical treatment to
one over WhatsApp, so the tests should look the same.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from baton.api import email_inbound
from baton.conversation.state import get_state

from .test_engine import _delete_test_workflows, _lead


def _comm(lead, sent_or_received, baton_author=None, content="hello"):
    doc = frappe.get_doc({
        "doctype": "Communication",
        "communication_type": "Communication",
        "communication_medium": "Email",
        "sent_or_received": sent_or_received,
        "subject": "Re: enquiry",
        "content": content,
        "reference_doctype": "CRM Lead",
        "reference_name": lead.name,
    })
    if baton_author is not None:
        doc.baton_author = baton_author
    doc.insert(ignore_permissions=True)
    return doc


class TestTagAuthor(FrappeTestCase):
    def setUp(self):
        self.lead = _lead()

    def tearDown(self):
        _delete_test_workflows()

    def test_received_is_tagged_contact(self):
        doc = _comm(self.lead, "Received")
        self.assertEqual(doc.baton_author, "contact")

    def test_sent_with_no_ai_flag_is_tagged_human(self):
        doc = _comm(self.lead, "Sent")
        self.assertEqual(doc.baton_author, "human")

    def test_sent_with_ai_flag_is_tagged_ai(self):
        frappe.flags.baton_ai_email = True
        try:
            doc = _comm(self.lead, "Sent")
        finally:
            frappe.flags.baton_ai_email = False
        self.assertEqual(doc.baton_author, "ai")

    def test_an_explicitly_set_author_is_never_overwritten(self):
        """The engine sets this itself in some paths; tag_author must not clobber it."""
        doc = _comm(self.lead, "Sent", baton_author="ai")
        self.assertEqual(doc.baton_author, "ai")

    def test_a_non_communication_row_is_left_alone(self):
        doc = frappe.get_doc({"doctype": "Communication", "communication_type": "Automated Message",
                              "communication_medium": "Email", "sent_or_received": "Sent",
                              "subject": "x", "content": "x"}).insert(ignore_permissions=True)
        self.assertFalse(doc.get("baton_author"))


class TestOnCommunication(FrappeTestCase):
    def setUp(self):
        self.lead = _lead()

    def tearDown(self):
        _delete_test_workflows()

    def test_contact_reply_marks_inbound(self):
        _comm(self.lead, "Received")
        st = get_state("CRM Lead", self.lead.name, create=False)
        self.assertIsNotNone(st)
        self.assertIsNotNone(st.last_inbound_at)

    def test_contact_reply_wakes_nothing_starts_no_bot_when_none_configured(self):
        # No parked run and no Inbound Message bot on this site -- should not
        # raise, and should simply do nothing further.
        _comm(self.lead, "Received")  # must not throw

    def test_human_send_pauses_the_conversation(self):
        _comm(self.lead, "Sent")  # no ai flag -> tagged human
        st = get_state("CRM Lead", self.lead.name, create=False)
        self.assertEqual(st.state, "HUMAN_ACTIVE")
        self.assertIsNotNone(st.paused_until)

    def test_ai_send_marks_ai_sent_and_does_not_pause(self):
        frappe.flags.baton_ai_email = True
        try:
            _comm(self.lead, "Sent")
        finally:
            frappe.flags.baton_ai_email = False
        st = get_state("CRM Lead", self.lead.name, create=False)
        self.assertIsNotNone(st)
        self.assertNotEqual(st.state, "HUMAN_ACTIVE")

    def test_contact_reply_requalifies_a_lead_in_the_background(self):
        with patch("frappe.enqueue") as enqueue:
            _comm(self.lead, "Received")
        calls = [c for c in enqueue.call_args_list
                if c.args and c.args[0] == "baton.api.whatsapp.requalify"]
        self.assertTrue(calls, "requalify was not enqueued for an inbound email reply")
        self.assertEqual(calls[0].kwargs.get("lead"), self.lead.name)

    def test_a_row_with_no_reference_is_ignored(self):
        frappe.get_doc({
            "doctype": "Communication", "communication_type": "Communication",
            "communication_medium": "Email", "sent_or_received": "Received",
            "subject": "x", "content": "x",
        }).insert(ignore_permissions=True)  # must not throw


class TestAutomatedSenderFilter(FrappeTestCase):
    """crm.utils.create_lead_from_incoming_email has no sender filter at all --
    a bounce or a service notification becomes a real CRM Lead named after its
    subject line, unconditionally. This is Baton's own corrective pass: crm's
    hook always runs first (crm installs before baton), so by the time this
    fires the junk lead already exists, and the fix is to undo the create."""

    def tearDown(self):
        for name in frappe.get_all(
                "CRM Lead", filters={"email": ["like", "%@automated-test.example.com"]},
                pluck="name"):
            frappe.delete_doc("CRM Lead", name, force=True, ignore_permissions=True)

    def test_looks_automated_matches_known_bounce_patterns(self):
        for sender in ("mailer-daemon@googlemail.com", "postmaster@example.com",
                      "no-reply@accounts.google.com", "noreply@reddit.com",
                      "do-not-reply@example.com", "bounce@example.com",
                      "MAILER-DAEMON@Example.COM"):
            self.assertTrue(email_inbound._looks_automated(sender), sender)

    def test_looks_automated_leaves_real_addresses_alone(self):
        for sender in ("prithvi@consilio.example.com", "notifications-team@example.com", None, ""):
            self.assertFalse(email_inbound._looks_automated(sender), sender)

    def test_a_junk_lead_crm_just_created_is_removed(self):
        sender = "mailer-daemon@automated-test.example.com"
        lead = frappe.get_doc({
            "doctype": "CRM Lead", "first_name": "Mail", "last_name": "Delivery Subsystem",
            "email": sender,
        }).insert(ignore_permissions=True)

        frappe.get_doc({
            "doctype": "Communication", "communication_type": "Communication",
            "communication_medium": "Email", "sent_or_received": "Received",
            "sender": sender, "subject": "Delivery Status Notification (Failure)",
            "content": "bounced",
        }).insert(ignore_permissions=True)

        self.assertFalse(frappe.db.exists("CRM Lead", lead.name))

    def test_an_old_lead_sharing_the_address_is_left_alone(self):
        """Not every lead with a no-reply-shaped address was caused by this
        email -- an old one is somebody's actual data."""
        sender = "no-reply@automated-test.example.com"
        lead = frappe.get_doc({
            "doctype": "CRM Lead", "first_name": "Someone", "email": sender,
        }).insert(ignore_permissions=True)
        frappe.db.set_value("CRM Lead", lead.name, "creation",
                            frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-10))

        frappe.get_doc({
            "doctype": "Communication", "communication_type": "Communication",
            "communication_medium": "Email", "sent_or_received": "Received",
            "sender": sender, "subject": "x", "content": "x",
        }).insert(ignore_permissions=True)

        self.assertTrue(frappe.db.exists("CRM Lead", lead.name))

    def test_a_sent_email_from_an_automated_looking_address_is_not_touched(self):
        """The filter only ever applies to Received mail -- an outbound send
        must never be mistaken for something to clean up."""
        lead = _lead()
        frappe.flags.baton_ai_email = True
        try:
            doc = _comm(lead, "Sent")
        finally:
            frappe.flags.baton_ai_email = False
        self.assertTrue(frappe.db.exists("CRM Lead", lead.name))
        self.assertEqual(doc.baton_author, "ai")
