"""Connections API — configure WhatsApp channels from the CRM UI.

Two ways to reach WhatsApp, and a business should be able to pick without a
developer:

  * **Meta Cloud API** (official). Verified business, approved templates, a
    24-hour service window. Cannot see messages the owner types on their own
    phone.
  * **OpenWA** (self-hosted bridge). No window, no templates, and it *does* see
    the owner's own messages -- which is what makes human-handoff detection
    complete. Unofficial, with account-ban risk.

Secrets are never returned to the browser. Every read reports whether a
credential is set, never its value.
"""

import frappe
from frappe import _

import requests

CHANNEL_META = "meta"
CHANNEL_OPENWA = "openwa"


def _guard():
    frappe.only_for(["System Manager", "Sales Manager"])


def _has(doc, field):
    try:
        return bool(doc.get_password(field, raise_exception=False))
    except Exception:
        return False


# ------------------------------------------------------------------- reading

@frappe.whitelist()
def get_connections():
    """Everything the Connections page renders. No secrets."""
    _guard()
    s = frappe.get_cached_doc("Baton Settings")

    openwa = {
        "enabled": bool(s.get("openwa_enabled")),
        "base_url": s.get("openwa_base_url") or "http://localhost:2785",
        "session_id": s.get("openwa_session_id") or "",
        "has_api_key": _has(s, "openwa_api_key"),
        "has_webhook_secret": _has(s, "openwa_webhook_secret"),
    }

    accounts = []
    if frappe.db.exists("DocType", "WhatsApp Account"):
        for a in frappe.get_all(
            "WhatsApp Account",
            fields=["name", "account_name", "status", "phone_id", "business_id",
                    "app_id", "is_default_outgoing"],
            order_by="modified desc",
        ):
            doc = frappe.get_doc("WhatsApp Account", a.name)
            accounts.append({**a, "has_token": _has(doc, "token")})

    meta = {
        "installed": "frappe_whatsapp" in frappe.get_installed_apps(),
        "accounts": accounts,
        "has_app_secret": _has(s, "meta_app_secret"),
        "active": any(a["status"] == "Active" for a in accounts),
    }

    return {
        "active_channel": CHANNEL_OPENWA if openwa["enabled"] else CHANNEL_META,
        "openwa": openwa,
        "meta": meta,
        "ai_enabled": bool(s.get("ai_enabled")),
        "whatsapp_send_mode": s.get("whatsapp_send_mode") or "Draft",
    }


# ------------------------------------------------------------------- OpenWA

@frappe.whitelist()
def save_openwa(base_url=None, api_key=None, session_id=None):
    """Persist OpenWA config. A blank api_key leaves the stored one alone."""
    _guard()
    s = frappe.get_single("Baton Settings")
    if base_url is not None:
        s.openwa_base_url = base_url.strip().rstrip("/")
    if session_id is not None:
        s.openwa_session_id = session_id.strip()
    if api_key:
        s.openwa_api_key = api_key.strip()
    s.save(ignore_permissions=True)
    frappe.db.commit()
    frappe.clear_cache(doctype="Baton Settings")
    return get_connections()


@frappe.whitelist()
def list_openwa_sessions(base_url=None, api_key=None):
    """Sessions available on an OpenWA server, so the UI can offer a picker.

    Accepts credentials inline so the page can validate before saving.
    """
    _guard()
    s = frappe.get_cached_doc("Baton Settings")
    url = (base_url or s.get("openwa_base_url") or "http://localhost:2785").rstrip("/")
    key = api_key or s.get_password("openwa_api_key", raise_exception=False)
    if not key:
        return {"ok": False, "error": "No API key provided or stored."}

    try:
        r = requests.get(f"{url}/api/sessions",
                         headers={"X-API-Key": key}, timeout=15)
    except Exception as e:
        return {"ok": False, "error": f"Cannot reach {url}: {str(e)[:160]}"}

    if r.status_code == 401:
        return {"ok": False, "error": "API key rejected by OpenWA."}
    if r.status_code >= 400:
        return {"ok": False, "error": f"OpenWA returned {r.status_code}: {r.text[:160]}"}

    body = r.json()
    rows = body if isinstance(body, list) else body.get("data") or []
    return {
        "ok": True,
        "sessions": [
            {"id": x.get("id"), "name": x.get("name"), "status": x.get("status"),
             "phone": x.get("phone"), "pushName": x.get("pushName")}
            for x in rows
        ],
    }


@frappe.whitelist()
def test_openwa():
    _guard()
    from baton.channels import openwa
    try:
        return openwa.session_status()
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


@frappe.whitelist()
def register_openwa_webhook(public_url):
    _guard()
    from baton.channels import openwa
    return openwa.register_webhook(public_url)


@frappe.whitelist()
def suggest_webhook_url():
    """Best guess at a URL OpenWA can reach Baton on.

    A container cannot resolve the host's `localhost`; on Docker Desktop
    `host.docker.internal` is the bridge. Anything non-local needs a real
    public URL or a tunnel.
    """
    site_url = frappe.utils.get_url()
    if "localhost" in site_url or "127.0.0.1" in site_url:
        port = site_url.rsplit(":", 1)[-1] if ":" in site_url.rsplit("/", 1)[-1] else "8000"
        return {"url": f"http://host.docker.internal:{port}",
                "note": "Docker Desktop bridges the host as host.docker.internal. "
                        "For a remote OpenWA you need a public URL or a tunnel."}
    return {"url": site_url, "note": "Using this site's configured URL."}


# --------------------------------------------------------------------- Meta

@frappe.whitelist()
def save_meta(app_secret=None, account=None, account_name=None, phone_id=None,
              business_id=None, app_id=None, token=None, status=None):
    """Persist Meta Cloud API config onto WhatsApp Account + Baton Settings."""
    _guard()
    if app_secret:
        s = frappe.get_single("Baton Settings")
        s.meta_app_secret = app_secret.strip()
        s.save(ignore_permissions=True)
        frappe.clear_cache(doctype="Baton Settings")

    if not frappe.db.exists("DocType", "WhatsApp Account"):
        frappe.db.commit()
        return get_connections()

    if account and frappe.db.exists("WhatsApp Account", account):
        doc = frappe.get_doc("WhatsApp Account", account)
    else:
        doc = frappe.new_doc("WhatsApp Account")
        doc.account_name = account_name or "Meta Cloud API"
        doc.url = "https://graph.facebook.com"
        doc.version = "v21.0"
        doc.webhook_verify_token = frappe.generate_hash(length=24)

    for field, value in (("phone_id", phone_id), ("business_id", business_id),
                         ("app_id", app_id), ("account_name", account_name)):
        if value:
            setattr(doc, field, value.strip())
    if token:
        doc.token = token.strip()
    if status:
        doc.status = status
    doc.is_default_outgoing = 1
    doc.is_default_incoming = 1
    doc.save(ignore_permissions=True)

    if frappe.db.exists("DocType", "WhatsApp Settings"):
        ws = frappe.get_single("WhatsApp Settings")
        ws.default_outgoing_account = doc.name
        ws.save(ignore_permissions=True)

    frappe.db.commit()
    return get_connections()


@frappe.whitelist()
def test_meta(account=None):
    """Ask Meta who this token belongs to -- the cheapest real check."""
    _guard()
    name = account or frappe.db.get_value("WhatsApp Account", {"is_default_outgoing": 1}, "name")
    if not name:
        return {"ok": False, "error": "No WhatsApp Account configured."}

    doc = frappe.get_doc("WhatsApp Account", name)
    token = doc.get_password("token", raise_exception=False)
    if not token:
        return {"ok": False, "error": "No access token set on this account."}
    if not doc.phone_id:
        return {"ok": False, "error": "No phone number ID set."}

    try:
        r = requests.get(
            f"{(doc.url or 'https://graph.facebook.com').rstrip('/')}/{doc.version or 'v21.0'}/{doc.phone_id}",
            headers={"Authorization": f"Bearer {token}"}, timeout=20,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

    if r.status_code >= 400:
        return {"ok": False, "error": f"{r.status_code}: {r.text[:250]}"}
    body = r.json()
    return {"ok": True, "display_name": body.get("verified_name") or body.get("display_phone_number"),
            "number": body.get("display_phone_number"), "quality": body.get("quality_rating")}


# ------------------------------------------------------------------ channel

@frappe.whitelist()
def set_active_channel(channel):
    """Switch which bridge outbound WhatsApp uses."""
    _guard()
    if channel not in (CHANNEL_META, CHANNEL_OPENWA):
        frappe.throw(_("Unknown channel {0}").format(channel))

    s = frappe.get_single("Baton Settings")
    s.openwa_enabled = 1 if channel == CHANNEL_OPENWA else 0
    s.save(ignore_permissions=True)
    frappe.db.commit()
    # clear_cache(doctype=...) drops the meta cache, not the document. Every
    # reader of this flag goes through get_cached_doc, so without the line below
    # the switch appears to work and nothing actually changes channel.
    frappe.clear_document_cache("Baton Settings", "Baton Settings")
    frappe.clear_cache(doctype="Baton Settings")

    from baton.audit import log_action
    log_action("connection.channel_changed", actor_type="HUMAN",
               decision=channel, reason=f"WhatsApp channel switched to {channel}")
    return get_connections()


@frappe.whitelist()
def set_send_mode(mode):
    _guard()
    if mode not in ("Auto", "Draft", "Off"):
        frappe.throw(_("Unknown mode {0}").format(mode))
    s = frappe.get_single("Baton Settings")
    s.whatsapp_send_mode = mode
    s.save(ignore_permissions=True)
    frappe.db.commit()
    frappe.clear_cache(doctype="Baton Settings")
    return get_connections()


# --------------------------------------------------------------- AI models
#
# Model credentials belong beside channel credentials: both are "how Baton
# reaches the outside world", both are secrets, and both are things a builder
# selects rather than defines. The builder links here; it never shows a key.

MODEL_FIELDS = ("model_name", "enabled", "is_default", "purpose", "provider",
                "model", "base_url", "api_version", "temperature", "max_tokens",
                "timeout")


@frappe.whitelist()
def set_ai_enabled(enabled):
    """The master switch, which had no UI at all.

    Everything Baton does that calls a model or writes to a customer is behind
    this. It shipped off and could only be turned on from Desk, which meant the
    product's own settings page could not finish setting the product up.
    """
    _guard()
    value = 1 if str(enabled) in ("1", "true", "True") else 0
    frappe.db.set_single_value("Baton Settings", "ai_enabled", value)
    frappe.db.commit()
    # The send gate reads through get_cached_doc, so the flip has to invalidate
    # the cached Single or nothing notices until the next restart.
    frappe.clear_document_cache("Baton Settings", "Baton Settings")
    return get_connections()


@frappe.whitelist()
def get_models():
    _guard()
    rows = frappe.get_all("Baton AI Model", fields=list(MODEL_FIELDS),
                          order_by="is_default desc, model_name")
    for r in rows:
        r["has_api_key"] = bool(
            frappe.utils.password.get_decrypted_password(
                "Baton AI Model", r["model_name"], "api_key", raise_exception=False)
        )
    return rows


@frappe.whitelist()
def save_model(model_name=None, api_key=None, **values):
    """Create or update one model credential. A blank key keeps the stored one."""
    _guard()
    if model_name and frappe.db.exists("Baton AI Model", model_name):
        doc = frappe.get_doc("Baton AI Model", model_name)
    else:
        doc = frappe.new_doc("Baton AI Model")
        doc.model_name = values.get("new_name") or model_name or "Model"

    for field in MODEL_FIELDS:
        if field in values and field != "model_name":
            doc.set(field, values[field])
    if api_key:
        doc.api_key = api_key
    doc.save(ignore_permissions=True)

    # Exactly one default, or "which model did it use?" has no answer.
    if doc.is_default:
        frappe.db.sql("""UPDATE `tabBaton AI Model` SET is_default = 0
                         WHERE name != %s""", (doc.name,))
    frappe.db.commit()
    return get_models()


@frappe.whitelist()
def delete_model(model_name):
    _guard()
    frappe.delete_doc("Baton AI Model", model_name, ignore_permissions=True)
    frappe.db.commit()
    return get_models()


@frappe.whitelist()
def test_model(model_name):
    _guard()
    from baton.llm import test_model as run_test

    try:
        return run_test(model_name)
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
