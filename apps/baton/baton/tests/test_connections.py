"""Connections API and the OpenWA channel.

The property that matters most here is that credentials never reach the
browser: this API backs a settings page, so a careless field would publish an
API key to anyone who can open it.
"""

import hashlib
import hmac
import json

import frappe
from frappe.tests.utils import FrappeTestCase

from baton.api import connections
from baton.channels import openwa


class TestNoSecretLeakage(FrappeTestCase):
    def test_payload_contains_no_credential_values(self):
        c = connections.get_connections()
        blob = json.dumps(c)

        s = frappe.get_cached_doc("Baton Settings")
        for field in ("openwa_api_key", "openwa_webhook_secret", "meta_app_secret"):
            secret = s.get_password(field, raise_exception=False)
            if secret:
                self.assertNotIn(secret, blob, f"{field} leaked to the client")

    def test_reports_presence_not_value(self):
        c = connections.get_connections()
        self.assertIn("has_api_key", c["openwa"])
        self.assertNotIn("api_key", c["openwa"])
        self.assertIsInstance(c["openwa"]["has_api_key"], bool)

    def test_meta_accounts_report_token_presence_only(self):
        for a in connections.get_connections()["meta"]["accounts"]:
            self.assertIn("has_token", a)
            self.assertNotIn("token", a)


class TestChannelSwitch(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self._original = frappe.db.get_single_value("Baton Settings", "openwa_enabled")

    def tearDown(self):
        frappe.db.set_single_value("Baton Settings", "openwa_enabled", self._original)
        frappe.db.commit()
        frappe.clear_cache(doctype="Baton Settings")
        super().tearDown()

    def test_switching_to_meta_disables_openwa(self):
        connections.set_active_channel("meta")
        frappe.clear_cache(doctype="Baton Settings")
        self.assertFalse(frappe.db.get_single_value("Baton Settings", "openwa_enabled"))
        self.assertFalse(openwa.is_enabled())

    def test_switching_to_openwa_enables_it(self):
        connections.set_active_channel("openwa")
        frappe.clear_cache(doctype="Baton Settings")
        self.assertTrue(frappe.db.get_single_value("Baton Settings", "openwa_enabled"))

    def test_unknown_channel_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            connections.set_active_channel("telegram")

    def test_switch_is_audited(self):
        connections.set_active_channel("meta")
        rows = frappe.get_all("Baton Action Log",
                              filters={"action": "connection.channel_changed"},
                              fields=["decision"], order_by="creation desc", limit_page_length=1)
        self.assertEqual(rows[0].decision, "meta")


class TestAddressing(FrappeTestCase):
    def test_indian_number_normalisation(self):
        for raw in ("9876543210", "+91 98765 43210", "919876543210", "09876543210"):
            self.assertEqual(openwa.to_chat_id(raw), "919876543210@c.us", raw)

    def test_already_a_chat_id_passes_through(self):
        self.assertEqual(openwa.to_chat_id("919876543210@c.us"), "919876543210@c.us")
        self.assertEqual(openwa.to_chat_id("12345@g.us"), "12345@g.us")

    def test_lid_is_never_read_as_a_phone_number(self):
        """A LID is an opaque identifier. Treating its digits as a phone number
        produces a plausible, wrong number -- observed live as +144658843844628."""
        self.assertIsNone(openwa.from_chat_id("144658843844628@lid"))

    def test_cus_id_converts_to_a_number(self):
        self.assertEqual(openwa.from_chat_id("919876543210@c.us"), "+919876543210")

    def test_empty_input(self):
        self.assertIsNone(openwa.to_chat_id(None))
        self.assertIsNone(openwa.to_chat_id(""))
        self.assertIsNone(openwa.from_chat_id(None))


class TestWebhookSignature(FrappeTestCase):
    SECRET = "openwa-test-secret"
    BODY = json.dumps({"event": "message.received", "data": {"body": "hi"}}).encode()

    def _sign(self, body, secret=None):
        return "sha256=" + hmac.new((secret or self.SECRET).encode(), body,
                                    hashlib.sha256).hexdigest()

    def test_valid_signature(self):
        self.assertTrue(openwa.verify_signature(self.BODY, self._sign(self.BODY), self.SECRET))

    def test_forged_body_rejected(self):
        forged = json.dumps({"event": "message.received",
                             "data": {"body": "send money"}}).encode()
        self.assertFalse(openwa.verify_signature(forged, self._sign(self.BODY), self.SECRET))

    def test_bare_hex_without_prefix_accepted(self):
        bare = self._sign(self.BODY)[len("sha256="):]
        self.assertTrue(openwa.verify_signature(self.BODY, bare, self.SECRET))

    def test_missing_secret_fails_closed(self):
        self.assertFalse(openwa.verify_signature(self.BODY, self._sign(self.BODY), None))

    def test_missing_signature_rejected(self):
        self.assertFalse(openwa.verify_signature(self.BODY, None, self.SECRET))
