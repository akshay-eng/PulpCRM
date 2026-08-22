"""Meta's 24-hour service window (spec §14).

Outside the window a business may only send an approved template; free-form
text is rejected by Meta and, worse, billed differently. The workflow engine
must know which branch applies *before* composing, or it will write messages it
cannot send.
"""

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

SERVICE_WINDOW_HOURS = 24


def window_state(reference_doctype, reference_name):
    """Return (free_form_allowed, expires_at, reason)."""
    from baton.conversation.thread import last_inbound_at

    last_in = last_inbound_at(reference_doctype, reference_name, channel="WhatsApp")
    if not last_in:
        return False, None, (
            "No inbound WhatsApp message on record, so the 24-hour service "
            "window has never opened. A template is required."
        )

    expires = add_to_date(get_datetime(last_in), hours=SERVICE_WINDOW_HOURS)
    if now_datetime() < expires:
        return True, expires, f"Service window open until {expires}"
    return False, expires, (
        f"Service window closed at {expires} (last inbound {last_in}). "
        "A template is required."
    )


def approved_templates():
    """Templates Meta has approved, if the WhatsApp app is installed."""
    if not frappe.db.exists("DocType", "WhatsApp Templates"):
        return []
    return frappe.get_all(
        "WhatsApp Templates",
        filters={"status": "APPROVED"},
        fields=["name", "template_name", "language", "category"],
    )


def _openwa_active():
    """Is WhatsApp currently going out through the self-hosted bridge?

    Deferred to channels.openwa so there is exactly one definition of "OpenWA is
    on". A looser test here would skip Meta's window check while the message
    still went to Meta -- which is the precise failure this check exists to
    prevent.
    """
    try:
        from baton.channels import openwa

        return openwa.is_enabled()
    except Exception:
        return False


def choose_send_mode(reference_doctype, reference_name, template=None):
    """Decide how a WhatsApp message must be sent right now.

    Returns dict: {mode: 'free_form'|'template'|'blocked', template, reason,
    expires_at, costs_template}
    """
    # The service window is Meta's rule, not WhatsApp's. OpenWA rides the real
    # account, so there is no window and no templates -- applying Meta's limits
    # there would block every first message for no reason at all.
    if _openwa_active():
        return {"mode": "free_form", "template": None,
                "reason": "OpenWA is active; Meta's 24-hour window does not apply.",
                "expires_at": None, "costs_template": False}

    allowed, expires, reason = window_state(reference_doctype, reference_name)

    if allowed:
        return {"mode": "free_form", "template": None, "reason": reason,
                "expires_at": expires, "costs_template": False}

    if template:
        return {"mode": "template", "template": template, "reason": reason,
                "expires_at": expires, "costs_template": True}

    available = approved_templates()
    if not available:
        return {"mode": "blocked", "template": None,
                "reason": reason + " No approved template is configured.",
                "expires_at": expires, "costs_template": False}

    return {"mode": "template", "template": available[0].name, "reason": reason,
            "expires_at": expires, "costs_template": True}
