"""Google sign-in, and sending mail from a person's own Gmail.

Two separate things that both start from one pair of Google Cloud credentials,
and which Frappe supports natively but leaves in Desk:

  * **Sign in with Google** -- a `Social Login Key`, site-wide, one switch.
  * **Send as me** -- a `Connected App` holding the OAuth client, plus a
    per-user `Token Cache` and an `Email Account` bound to that user. This is
    what makes mail leave *their* mailbox rather than a shared one.

The client secret is written once and never read back. Everything this module
returns is either a boolean, a redirect URL, or a URI the user has to paste into
Google Cloud -- never a credential.
"""

import frappe
from frappe import _
from frappe.utils import get_url

CONNECTED_APP = "Google Mail"

# Connected App has no autoname, so its document name is a hash and the
# provider name is the only stable handle.
def _mail_app():
    name = frappe.db.get_value("Connected App", {"provider_name": CONNECTED_APP}, "name")
    return frappe.get_doc("Connected App", name) if name else None
GMAIL_SCOPE = "https://mail.google.com/"

AUTHORIZATION_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
REVOCATION_URI = "https://oauth2.googleapis.com/revoke"
USERINFO_URI = "https://openidconnect.googleapis.com/v1/userinfo"


def _guard():
    frappe.only_for(["System Manager", "Sales Manager"])


def redirect_uris():
    """Exactly what has to go in Google Cloud's "Authorised redirect URIs".

    Two of them, because sign-in and mail are different OAuth flows in Frappe
    and each has its own callback. Configuring one and not the other produces a
    redirect_uri_mismatch that says nothing about which half is wrong, so both
    are shown together.

    The mail one is read back off the Connected App rather than composed here:
    Frappe builds it in `ConnectedApp.validate` and appends the document name,
    so a guess would be subtly wrong and fail only at consent time.
    """
    base = get_url().rstrip("/")
    app = _mail_app()
    return {
        "login": f"{base}/api/method/frappe.integrations.oauth2_logins.login_via_google",
        "mail": app.redirect_uri if app else None,
        "origin": base,
    }


@frappe.whitelist()
def get_google_status():
    """What is set up, and what is still missing. No secrets."""
    _guard()

    settings = frappe.get_single("Google Settings")
    has_secret = bool(frappe.utils.password.get_decrypted_password(
        "Google Settings", "Google Settings", "client_secret", raise_exception=False))

    login = frappe.db.get_value(
        "Social Login Key", {"social_login_provider": "Google"},
        ["name", "enable_social_login", "client_id"], as_dict=True)

    doc = _mail_app()
    app = {"name": doc.name, "client_id": doc.client_id,
           "has_secret": bool(frappe.utils.password.get_decrypted_password(
               "Connected App", doc.name, "client_secret", raise_exception=False))} \
        if doc else None

    return {
        "client_id": settings.client_id or "",
        "has_client_secret": has_secret,
        "enabled": bool(settings.enable),
        "login_enabled": bool(login and login.enable_social_login),
        "mail_app": app,
        "redirect_uris": redirect_uris(),
        "my_account": my_gmail_status(),
    }


@frappe.whitelist()
def save_google(client_id=None, client_secret=None, enable_login=None):
    """Store the Google Cloud client, and wire up both flows from it.

    One pair of credentials drives sign-in and mail; asking for them twice is
    how people end up with two half-configured apps and a mismatch error.
    """
    _guard()

    settings = frappe.get_single("Google Settings")
    if client_id is not None:
        settings.client_id = (client_id or "").strip()
    if client_secret:
        settings.client_secret = client_secret
    settings.enable = 1
    settings.save(ignore_permissions=True)

    secret = frappe.utils.password.get_decrypted_password(
        "Google Settings", "Google Settings", "client_secret", raise_exception=False)

    _sync_social_login(settings.client_id, secret,
                       enabled=1 if str(enable_login) in ("1", "true", "True") else 0)
    _sync_connected_app(settings.client_id, secret)

    frappe.db.commit()
    return get_google_status()


def _sync_social_login(client_id, secret, enabled):
    """Create or update the Google Social Login Key.

    Frappe already knows Google's URLs and scopes, so the provider is
    initialised from its own table rather than from constants copied here that
    would rot the moment Google moves an endpoint.
    """
    name = frappe.db.get_value("Social Login Key",
                               {"social_login_provider": "Google"}, "name")
    doc = frappe.get_doc("Social Login Key", name) if name \
        else frappe.new_doc("Social Login Key")

    if not name:
        doc.get_social_login_provider("Google", initialize=True)
        doc.social_login_provider = "Google"

    doc.client_id = client_id
    if secret:
        doc.client_secret = secret
    doc.enable_social_login = enabled
    # Deny by default: a Google login that silently creates accounts turns any
    # Google address into a CRM user.
    doc.sign_ups = doc.sign_ups or "Deny"
    doc.save(ignore_permissions=True)


def _sync_connected_app(client_id, secret):
    """The OAuth client used to send mail as a person."""
    doc = _mail_app()
    if not doc:
        doc = frappe.new_doc("Connected App")
        doc.provider_name = CONNECTED_APP

    doc.client_id = client_id
    if secret:
        doc.client_secret = secret
    doc.authorization_uri = AUTHORIZATION_URI
    doc.token_uri = TOKEN_URI
    doc.revocation_uri = REVOCATION_URI
    doc.userinfo_uri = USERINFO_URI
    # redirect_uri is not ours to set: ConnectedApp.validate composes it from
    # the site URL and the document name.

    if not any(s.scope == GMAIL_SCOPE for s in doc.get("scopes") or []):
        doc.append("scopes", {"scope": GMAIL_SCOPE})

    # Google only returns a refresh token when asked, and only the first time
    # unless consent is forced. Without both, sending works today and stops
    # working in an hour when the access token expires.
    have = {q.key for q in doc.get("query_parameters") or []}
    for key, value in (("access_type", "offline"), ("prompt", "consent")):
        if key not in have:
            doc.append("query_parameters", {"key": key, "value": value})

    doc.save(ignore_permissions=True)


# ------------------------------------------------------- per-user mail access

def my_gmail_status(user=None):
    """Has this person connected their own mailbox?"""
    user = user or frappe.session.user
    app = _mail_app()
    if not app:
        return {"connected": False, "email_account": None, "ready": False}

    token = frappe.db.exists("Token Cache", f"{app.name}-{user}")
    account = frappe.db.get_value(
        "Email Account",
        {"connected_user": user, "auth_method": "OAuth", "service": "GMail"},
        ["name", "email_id", "enable_outgoing", "default_outgoing"], as_dict=True)

    return {
        "connected": bool(token),
        "email_account": account,
        "ready": bool(token and account and account.enable_outgoing),
    }


@frappe.whitelist()
def connect_my_gmail(email_id, make_default=0):
    """Start the consent flow for the signed-in user's own mailbox.

    Returns the URL to send them to. The Email Account is created first, so the
    token has somewhere to belong when they come back -- creating it afterwards
    means a successful consent that leaves nothing usable behind.
    """
    app = _mail_app()
    if not app:
        frappe.throw(_("Google is not set up yet. Add the client ID and secret first."))

    email_id = (email_id or "").strip()
    if not email_id:
        frappe.throw(_("Which address? Give the Gmail address you want to send from."))

    user = frappe.session.user
    name = frappe.db.get_value(
        "Email Account", {"connected_user": user, "email_id": email_id}, "name")
    doc = frappe.get_doc("Email Account", name) if name else frappe.new_doc("Email Account")

    doc.email_account_name = doc.email_account_name or f"Gmail - {email_id}"
    doc.email_id = email_id
    doc.service = "GMail"
    doc.auth_method = "OAuth"
    doc.connected_app = app.name
    doc.connected_user = user
    doc.enable_outgoing = 1
    doc.smtp_server = "smtp.gmail.com"
    doc.smtp_port = 587
    doc.use_tls = 1
    if int(make_default or 0):
        doc.default_outgoing = 1
    doc.flags.ignore_mandatory = True
    # The account cannot be validated until the token exists, and the token
    # cannot exist until the account does.
    doc.flags.ignore_validate = True
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {"url": app.initiate_web_application_flow(user=user), "account": doc.name}


@frappe.whitelist()
def disconnect_my_gmail():
    """Drop the stored token. The Email Account is left alone."""
    user = frappe.session.user
    app = _mail_app()
    if not app:
        return my_gmail_status()
    token = f"{app.name}-{user}"
    if frappe.db.exists("Token Cache", token):
        frappe.delete_doc("Token Cache", token, force=True, ignore_permissions=True)
        frappe.db.commit()
    return my_gmail_status()


@frappe.whitelist()
def sending_accounts():
    """Addresses a bot may be told to send from.

    Only accounts that can actually send, so the picker cannot offer something
    that fails at the first run.
    """
    _guard()
    return frappe.get_all(
        "Email Account",
        filters={"enable_outgoing": 1},
        fields=["name", "email_id", "default_outgoing", "auth_method", "connected_user"],
        order_by="default_outgoing desc, email_id",
    )
