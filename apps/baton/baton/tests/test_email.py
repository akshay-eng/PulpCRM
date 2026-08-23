"""Immediate delivery of queued mail.

Frappe hands outbound mail to the scheduler, which flushes every 240 seconds by
default. Someone presses Send on a deal, nothing happens for four minutes, and
they conclude email is broken — which is exactly what happened here.

These tests pin the guards, not the speed: the point is that sending sooner must
not mean sending twice.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from baton.api import email as baton_email


def _queue(**kw):
    values = {
        "doctype": "Email Queue",
        "sender": "sender@example.com",
        "message": "hello",
        "status": "Not Sent",
        "priority": 1,
    }
    values.update(kw)
    doc = frappe.get_doc(values)
    doc.append("recipients", {"recipient": "someone@example.com", "status": "Not Sent"})
    doc.insert(ignore_permissions=True)
    return doc


class TestImmediateSendGuards(FrappeTestCase):
    """send_now decides whether to hand a row to a worker. Every refusal here
    is a case where sending immediately would be wrong."""

    def _enqueued(self, doc):
        calls = []
        original = frappe.enqueue

        def spy(*a, **kw):
            calls.append(kw.get("queue_name"))

        frappe.enqueue = spy
        try:
            baton_email.send_now(doc)
        finally:
            frappe.enqueue = original
        return calls

    def setUp(self):
        super().setUp()
        # send_now no-ops under in_test so the suite never sends mail; these
        # tests exercise the decision directly with the flag lifted.
        self._flag = frappe.flags.in_test
        self._mute = frappe.flags.mute_emails
        self._suspended = frappe.db.get_default("suspend_email_queue")
        frappe.flags.in_test = False
        # before_tests mutes the suite two ways, and send_now honours both.
        # These tests are about the *other* decisions send_now makes, so they
        # lift both guards and put them back in tearDown. Nothing is delivered
        # either way: _enqueued() replaces frappe.enqueue with a spy, so the
        # worker is never handed anything.
        frappe.flags.mute_emails = False
        frappe.db.set_default("suspend_email_queue", 0)

    def tearDown(self):
        frappe.flags.in_test = self._flag
        frappe.flags.mute_emails = self._mute
        frappe.db.set_default("suspend_email_queue", self._suspended or 0)
        super().tearDown()

    def test_a_new_unsent_row_is_handed_to_a_worker(self):
        doc = _queue()
        self.assertEqual(self._enqueued(doc), [doc.name])

    def test_an_already_sent_row_is_left_alone(self):
        doc = _queue()
        doc.status = "Sent"
        self.assertEqual(self._enqueued(doc), [])

    def test_a_future_send_stays_scheduled(self):
        """A send_after in the future was scheduled on purpose."""
        doc = _queue(send_after=add_to_date(now_datetime(), hours=2))
        self.assertEqual(self._enqueued(doc), [])

    def test_a_past_send_after_still_goes(self):
        doc = _queue(send_after=add_to_date(now_datetime(), hours=-1))
        self.assertEqual(self._enqueued(doc), [doc.name])

    def test_muted_emails_are_not_sent_immediately(self):
        """The setting that silently swallowed sends for a whole debugging
        session. If it is on, immediate delivery must respect it too."""
        doc = _queue()
        original = frappe.flags.mute_emails
        frappe.flags.mute_emails = True
        try:
            self.assertEqual(self._enqueued(doc), [])
        finally:
            frappe.flags.mute_emails = original


class TestDeliverIsIdempotent(FrappeTestCase):
    def test_delivering_an_already_sent_row_does_nothing(self):
        """The scheduler and this worker can race for the same row; whichever
        loses must decline rather than send a second copy."""
        doc = _queue(status="Sent")
        sent = []
        original_send = frappe.get_doc("Email Queue", doc.name).__class__.send
        try:
            frappe.get_doc("Email Queue", doc.name).__class__.send = \
                lambda self, *a, **kw: sent.append(self.name)
            baton_email.deliver(doc.name)
        finally:
            frappe.get_doc("Email Queue", doc.name).__class__.send = original_send
        self.assertEqual(sent, [], "a sent email was sent again")

    def test_a_missing_row_is_not_an_error(self):
        baton_email.deliver("does-not-exist")  # must not raise
