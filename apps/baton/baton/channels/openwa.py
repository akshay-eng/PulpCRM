"""OpenWA connector — WhatsApp via a self-hosted account bridge.

Why this exists alongside the Meta path:

Meta's Cloud API cannot see messages a human types from their own phone. They
simply never reach the API. That makes BATON's central promise -- "a human
replies, the AI shuts up" -- only partly enforceable: we can detect a send we
did not make, but not a send that never touched us.

OpenWA rides the real account, so `message.sent` fires whether the API sent it
or the owner typed it on their phone. Correlating that against our own sends
gives genuine human-intervention detection rather than an inference.

Trade-off, stated plainly: this is an unofficial bridge to WhatsApp Web. It is
not Meta-sanctioned and carries account-ban risk. It also has no 24-hour service
window and no template requirement -- constraints that exist on the official API
and do not apply here.
"""

import hashlib
import hmac
import re

import frappe
import requests

DEFAULT_BASE_URL = "http://localhost:2785"
SIGNATURE_HEADER = "X-OpenWA-Signature"
TIMEOUT = 30


class OpenWANotConfigured(frappe.ValidationError):
    pass


def settings():
    return frappe.get_cached_doc("Baton Settings")


def is_enabled():
    s = settings()
    return bool(s.get("openwa_enabled") and s.get("openwa_session_id"))


def _cfg():
    s = settings()
    if not s.get("openwa_enabled"):
        raise OpenWANotConfigured("OpenWA is not enabled in Baton Settings.")
    key = s.get_password("openwa_api_key", raise_exception=False)
    if not key:
        raise OpenWANotConfigured("OpenWA API key is not set.")
    session = s.get("openwa_session_id")
    if not session:
        raise OpenWANotConfigured("OpenWA session ID is not set.")
    return (s.get("openwa_base_url") or DEFAULT_BASE_URL).rstrip("/"), key, session


def _headers(key):
    return {"X-API-Key": key, "Content-Type": "application/json"}


# ---------------------------------------------------------------- addressing

def to_chat_id(number):
    """Normalise a phone number to OpenWA's `<digits>@c.us` form.

    Indian numbers are frequently stored as '9812345678' or '+91 98123 45678'.
    A bare 10-digit number is assumed to be +91, because that is this product's
    market -- an assumption worth knowing about rather than one to hide.
    """
    if not number:
        return None
    number = str(number).strip()
    if number.endswith("@c.us") or number.endswith("@g.us"):
        return number

    digits = re.sub(r"\D", "", number)
    if not digits:
        return None
    if len(digits) == 10:
        digits = "91" + digits
    elif digits.startswith("0") and len(digits) == 11:
        digits = "91" + digits[1:]
    return f"{digits}@c.us"


def from_chat_id(chat_id):
    """`919812345678@c.us` -> `+919812345678`.

    Returns None for @lid ids: a LID is an opaque privacy identifier, NOT a
    phone number, and treating its digits as one silently addresses the wrong
    person. Use resolve_phone() for those.
    """
    if not chat_id:
        return None
    if str(chat_id).endswith("@lid"):
        return None
    digits = re.sub(r"\D", "", str(chat_id).split("@")[0])
    return f"+{digits}" if digits else None


def resolve_phone(chat_id):
    """Get a real phone number for any chat id, resolving @lid via OpenWA.

    WhatsApp is migrating to LID addressing, where the webhook carries no phone
    number at all. OpenWA keeps a persisted lid -> phone table and exposes it;
    without this, every LID-addressed conversation fails to match a CRM record.
    """
    if not chat_id:
        return None
    direct = from_chat_id(chat_id)
    if direct:
        return direct

    cached = frappe.cache().hget("baton_lid_phone", chat_id)
    if cached:
        return cached

    try:
        base, key, session = _cfg()
        r = requests.get(
            f"{base}/api/sessions/{session}/contacts/{chat_id}/phone",
            headers=_headers(key), timeout=15,
        )
        if r.status_code >= 400:
            return None
        phone = (r.json() or {}).get("phone")
        if not phone:
            return None
        normalised = "+" + re.sub(r"\D", "", str(phone))
        frappe.cache().hset("baton_lid_phone", chat_id, normalised)
        return normalised
    except Exception:
        return None


# ------------------------------------------------------------------ sending

def send_text(to, text, quoted_message_id=None):
    """Send a text message. Returns the OpenWA response dict."""
    base, key, session = _cfg()
    chat_id = to_chat_id(to)
    if not chat_id:
        frappe.throw(f"Cannot build a chat id from '{to}'")

    payload = {"chatId": chat_id, "text": (text or "")[:4096]}
    if quoted_message_id:
        payload["quotedMessageId"] = quoted_message_id

    r = requests.post(
        f"{base}/api/sessions/{session}/messages/send-text",
        headers=_headers(key), json=payload, timeout=TIMEOUT,
    )
    if r.status_code >= 400:
        frappe.throw(f"OpenWA send failed ({r.status_code}): {r.text[:400]}")
    return r.json()


# WhatsApp media type -> the content_type the CRM's WhatsApp tab renders.
MEDIA_CONTENT_TYPES = {
    "image": "image", "video": "video", "audio": "audio",
    "document": "document", "sticker": "image", "ptt": "audio",
}


def fetch_media(chat_id, message_id):
    """Download a message's media bytes from OpenWA.

    Webhook payloads shed media over a size cap and send
    `{"omitted": true, "sizeBytes": N}` instead, so the bytes must be pulled
    separately. Requires CHAT_MEDIA_ARCHIVE_ENABLED on the OpenWA side;
    without it this returns None and the message is kept as text.
    """
    import urllib.parse

    base, key, session = _cfg()
    chat = urllib.parse.quote(str(chat_id), safe="")
    msg = urllib.parse.quote(str(message_id), safe="")

    r = requests.get(
        f"{base}/api/sessions/{session}/messages/{chat}/{msg}/media",
        headers={"X-API-Key": key}, timeout=60,
    )
    if r.status_code != 200:
        return None
    content_type = (r.headers.get("Content-Type") or "").split(";")[0].strip()
    if content_type.startswith("application/json"):
        return None  # an error body, not media
    return {"content": r.content, "mimetype": content_type or "application/octet-stream"}


def session_status():
    base, key, session = _cfg()
    r = requests.get(f"{base}/api/sessions/{session}", headers=_headers(key), timeout=TIMEOUT)
    if r.status_code >= 400:
        return {"ok": False, "status": r.status_code, "error": r.text[:300]}
    data = r.json()
    return {"ok": True, "status": data.get("status"), "name": data.get("name"), "id": data.get("id")}


# ------------------------------------------------------------------ webhooks

def verify_signature(raw_body: bytes, header_value: str, secret: str) -> bool:
    """OpenWA signs as `sha256=<hex>` over the raw body -- same shape as Meta."""
    if not header_value or not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body or b"", hashlib.sha256).hexdigest()
    provided = header_value[len("sha256="):] if header_value.startswith("sha256=") else header_value
    return hmac.compare_digest(expected, provided)


@frappe.whitelist()
def register_webhook(public_url):
    """Point OpenWA at Baton's inbound endpoint, with a fresh shared secret."""
    frappe.only_for(["System Manager", "Sales Manager"])
    base, key, session = _cfg()

    secret = frappe.generate_hash(length=40)
    url = f"{public_url.rstrip('/')}/api/method/baton.api.openwa_webhook.inbound"

    r = requests.post(
        f"{base}/api/sessions/{session}/webhooks",
        headers=_headers(key),
        json={
            "url": url,
            # message.sent matters as much as message.received: it is how a
            # message typed on the owner's phone reaches us.
            "events": ["message.received", "message.sent", "message.ack"],
            "secret": secret,
            "retryCount": 3,
        },
        timeout=TIMEOUT,
    )
    if r.status_code >= 400:
        frappe.throw(f"OpenWA webhook registration failed ({r.status_code}): {r.text[:400]}")

    s = frappe.get_single("Baton Settings")
    s.openwa_webhook_secret = secret
    s.save(ignore_permissions=True)
    frappe.db.commit()

    body = r.json()
    return {"webhook_id": body.get("id"), "url": url, "events": body.get("events")}


@frappe.whitelist()
def test_connection():
    """Settings-page check: can we reach OpenWA and is the session ready?"""
    frappe.only_for(["System Manager", "Sales Manager"])
    try:
        return session_status()
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
