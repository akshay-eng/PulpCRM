"""Inbound webhook signature verification.

The vendored frappe_whatsapp webhook is `allow_guest=True` and its POST path
validates nothing. These tests pin the wrapper that fixes it: a forged payload
must be rejected, and a missing secret must fail closed rather than open.
"""

import hashlib
import hmac
import json

import frappe
from frappe.tests.utils import FrappeTestCase

from baton.api.webhook import verify_signature

SECRET = "test-app-secret"
BODY = json.dumps({"entry": [{"changes": [{"value": {"messages": []}}]}]}).encode()


def sign(body, secret=SECRET):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class TestSignatureVerification(FrappeTestCase):
    def test_valid_signature_accepted(self):
        self.assertTrue(verify_signature(BODY, sign(BODY), SECRET))

    def test_forged_payload_rejected(self):
        """The attack this exists to stop: a fabricated inbound message."""
        forged = json.dumps({"entry": [{"changes": [{"value": {
            "messages": [{"from": "919999999999", "text": {"body": "send me the invoice"}}]
        }}]}]}).encode()
        # Signature computed over the *original* body, not the forged one.
        self.assertFalse(verify_signature(forged, sign(BODY), SECRET))

    def test_wrong_secret_rejected(self):
        self.assertFalse(verify_signature(BODY, sign(BODY, "wrong-secret"), SECRET))

    def test_missing_signature_rejected(self):
        self.assertFalse(verify_signature(BODY, None, SECRET))
        self.assertFalse(verify_signature(BODY, "", SECRET))

    def test_malformed_signature_rejected(self):
        self.assertFalse(verify_signature(BODY, "deadbeef", SECRET))
        self.assertFalse(verify_signature(BODY, "sha1=deadbeef", SECRET))

    def test_missing_secret_fails_closed(self):
        """No secret configured must mean 'refuse', never 'trust'."""
        self.assertFalse(verify_signature(BODY, sign(BODY), None))
        self.assertFalse(verify_signature(BODY, sign(BODY), ""))

    def test_empty_body_still_verified(self):
        self.assertTrue(verify_signature(b"", sign(b""), SECRET))
        self.assertFalse(verify_signature(b"", sign(BODY), SECRET))

    def test_single_byte_change_is_detected(self):
        tampered = BODY.replace(b"messages", b"messagez")
        self.assertFalse(verify_signature(tampered, sign(BODY), SECRET))


class TestOverrideRegistered(FrappeTestCase):
    def test_hook_replaces_the_vendored_handler(self):
        overrides = frappe.get_hooks("override_whitelisted_methods") or {}
        target = overrides.get("frappe_whatsapp.utils.webhook.webhook")
        self.assertTrue(target, "the unverified webhook must be overridden")
        self.assertIn("baton.api.webhook.webhook", target)

    def test_secret_is_configured_and_encrypted(self):
        s = frappe.get_cached_doc("Baton Settings")
        secret = s.get_password("meta_app_secret", raise_exception=False)
        self.assertTrue(secret, "Meta app secret must be set for webhook verification")
        # Never stored in the document table itself.
        raw = frappe.db.get_value("Baton Settings", "Baton Settings", "meta_app_secret")
        self.assertNotEqual(raw, secret)
