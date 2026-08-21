"""Signature-verified wrapper around the WhatsApp inbound webhook.

`frappe_whatsapp.utils.webhook.webhook` is registered `allow_guest=True` and its
POST path validates nothing at all -- no signature, no shared secret, no replay
protection. Anyone who learns the URL can inject fabricated inbound messages,
and in an AI-driven CRM a forged message *drives the agent*.

This module verifies Meta's `X-Hub-Signature-256` HMAC before delegating to the
original handler. It is installed via `override_whitelisted_methods` rather than
by editing the vendored app, so upgrading frappe_whatsapp cannot silently drop
the check.
"""

import hashlib
import hmac

import frappe

SIGNATURE_HEADER = "X-Hub-Signature-256"


def _app_secret():
    return frappe.get_cached_doc("Baton Settings").get_password(
        "meta_app_secret", raise_exception=False
    )


def verify_signature(raw_body: bytes, header_value: str, app_secret: str) -> bool:
    """Constant-time check of Meta's sha256 HMAC over the raw request body."""
    if not header_value or not app_secret:
        return False
    if not header_value.startswith("sha256="):
        return False

    expected = hmac.new(
        app_secret.encode("utf-8"),
        raw_body or b"",
        hashlib.sha256,
    ).hexdigest()
    # compare_digest, never ==, so a timing side channel cannot leak the digest.
    return hmac.compare_digest(expected, header_value[len("sha256="):])


@frappe.whitelist(allow_guest=True)
def webhook():
    """Verified entry point. Same URL contract as the app it replaces."""
    from frappe_whatsapp.utils.webhook import get as wa_get
    from frappe_whatsapp.utils.webhook import post as wa_post

    if frappe.request.method == "GET":
        # The subscription handshake already validates hub.verify_token.
        return wa_get()

    secret = _app_secret()
    if not secret:
        # Fail closed. An unverifiable public endpoint is worse than an offline
        # one -- refusing is recoverable, accepting forgeries is not.
        frappe.throw(
            "Baton: BATON meta_app_secret is not configured; refusing unverified webhook.",
            frappe.PermissionError,
        )

    raw = frappe.request.get_data() or b""
    signature = frappe.get_request_header(SIGNATURE_HEADER)

    if not verify_signature(raw, signature, secret):
        from baton.audit import log_action

        log_action(
            "whatsapp.webhook_rejected",
            status="Failed",
            actor_type="SYSTEM",
            decision="REJECTED",
            reason="X-Hub-Signature-256 missing or invalid",
            output={
                "had_signature": bool(signature),
                "bytes": len(raw),
                "remote_addr": frappe.local.request_ip,
            },
        )
        # Commit before throwing. frappe.throw rolls the transaction back, which
        # would discard the very record of the rejected attempt -- leaving no
        # audit trail of an attack against a public endpoint.
        frappe.db.commit()
        frappe.throw("Invalid webhook signature.", frappe.PermissionError)

    return wa_post()
