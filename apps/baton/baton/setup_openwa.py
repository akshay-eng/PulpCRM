"""OpenWA connector settings."""

import frappe
from baton.setup_phase1 import _add_fields


def install():
    _add_fields("Baton Settings", [
        {"fieldname": "sec_openwa", "fieldtype": "Section Break", "label": "OpenWA (self-hosted WhatsApp)"},
        {"fieldname": "openwa_enabled", "fieldtype": "Check", "label": "Use OpenWA for WhatsApp",
         "default": "0",
         "description": "Routes WhatsApp through a self-hosted OpenWA bridge instead of Meta's "
                        "Cloud API. Unofficial: no 24h window and no templates, but it carries "
                        "account-ban risk."},
        {"fieldname": "openwa_base_url", "fieldtype": "Data", "label": "Base URL",
         "default": "http://localhost:2785"},
        {"fieldname": "openwa_session_id", "fieldtype": "Data", "label": "Session ID"},
        {"fieldname": "col_openwa", "fieldtype": "Column Break"},
        {"fieldname": "openwa_api_key", "fieldtype": "Password", "label": "API Key"},
        {"fieldname": "openwa_webhook_secret", "fieldtype": "Password", "label": "Webhook secret",
         "description": "Set automatically when the webhook is registered."},
    ])
    frappe.db.commit()
    print("OpenWA settings ready.")
