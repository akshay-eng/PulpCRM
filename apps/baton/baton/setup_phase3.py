"""Phase 3 — conversation state, human handoff and send policy.

    bench --site crm.localhost execute baton.setup_phase3.install
"""

import frappe

from baton.setup_phase1 import _add_fields, _doctype


def install():
    # ------------------------------------------------- conversation state
    # Spec §26: explicit states, not a boolean. "Is the AI allowed to speak
    # right now" must be answerable from one row, because every outbound send
    # consults it.
    _doctype(
        "Baton Conversation State",
        [
            {"fieldname": "reference_doctype", "fieldtype": "Link", "label": "Reference Type",
             "options": "DocType", "reqd": 1, "in_list_view": 1},
            {"fieldname": "reference_name", "fieldtype": "Dynamic Link", "label": "Reference",
             "options": "reference_doctype", "reqd": 1, "in_list_view": 1},
            {"fieldname": "col_s", "fieldtype": "Column Break"},
            {"fieldname": "state", "fieldtype": "Select", "label": "State", "default": "AI_ACTIVE",
             "options": "AI_ACTIVE\nHUMAN_ACTIVE\nAI_REVIEW_PENDING\nPAUSED\nESCALATED\nCLOSED\nDO_NOT_CONTACT",
             "in_list_view": 1, "in_standard_filter": 1},
            {"fieldname": "channel", "fieldtype": "Select", "label": "Channel",
             "options": "Any\nWhatsApp\nEmail", "default": "Any"},
            {"fieldname": "sec_pause", "fieldtype": "Section Break", "label": "Pause"},
            {"fieldname": "paused_until", "fieldtype": "Datetime", "label": "Paused until",
             "description": "AI may not send before this time."},
            {"fieldname": "paused_by", "fieldtype": "Link", "label": "Paused by", "options": "User"},
            {"fieldname": "pause_reason", "fieldtype": "Small Text", "label": "Reason"},
            {"fieldname": "col_p", "fieldtype": "Column Break"},
            {"fieldname": "resume_policy", "fieldtype": "Select", "label": "Resume policy",
             "options": "AUTO_RESUME\nREQUIRE_APPROVAL\nREMAIN_PAUSED", "default": "REQUIRE_APPROVAL"},
            {"fieldname": "sec_act", "fieldtype": "Section Break", "label": "Activity"},
            {"fieldname": "last_human_message_at", "fieldtype": "Datetime", "label": "Last human message"},
            {"fieldname": "last_ai_message_at", "fieldtype": "Datetime", "label": "Last AI message"},
            {"fieldname": "col_act", "fieldtype": "Column Break"},
            {"fieldname": "last_inbound_at", "fieldtype": "Datetime", "label": "Last inbound"},
            {"fieldname": "ai_turn_count", "fieldtype": "Int", "label": "AI turns", "default": "0"},
        ],
        autoname="hash",
    )

    # ------------------------------------------------------ automation policy
    # Spec §27, §51, §52, §60 — all configurable, none hardcoded.
    _add_fields("Baton Settings", [
        {"fieldname": "sec_auto", "fieldtype": "Section Break", "label": "Automation policy"},
        {"fieldname": "whatsapp_send_mode", "fieldtype": "Select", "label": "WhatsApp sending",
         "options": "Auto\nDraft\nOff", "default": "Auto",
         "description": "Draft composes but requires approval before sending (spec §59)."},
        {"fieldname": "email_send_mode", "fieldtype": "Select", "label": "Email sending",
         "options": "Auto\nDraft\nOff", "default": "Draft"},
        {"fieldname": "col_auto", "fieldtype": "Column Break"},
        {"fieldname": "human_cooldown_minutes", "fieldtype": "Int",
         "label": "Human intervention cooldown (minutes)", "default": "360",
         "description": "AI stays silent this long after a human sends manually."},
        {"fieldname": "default_resume_policy", "fieldtype": "Select", "label": "Default resume policy",
         "options": "AUTO_RESUME\nREQUIRE_APPROVAL\nREMAIN_PAUSED", "default": "REQUIRE_APPROVAL"},
        {"fieldname": "sec_quiet", "fieldtype": "Section Break", "label": "Quiet hours"},
        {"fieldname": "quiet_hours_enabled", "fieldtype": "Check", "label": "Enable quiet hours",
         "default": "1"},
        {"fieldname": "quiet_start", "fieldtype": "Time", "label": "Quiet from", "default": "22:00:00"},
        {"fieldname": "col_quiet", "fieldtype": "Column Break"},
        {"fieldname": "quiet_end", "fieldtype": "Time", "label": "Quiet until", "default": "08:00:00"},
        {"fieldname": "max_messages_per_lead_per_day", "fieldtype": "Int",
         "label": "Max automated messages per lead per day", "default": "3",
         "description": "Rate limit against runaway loops (spec §50)."},
        {"fieldname": "sec_meta", "fieldtype": "Section Break", "label": "Meta"},
        {"fieldname": "meta_app_secret", "fieldtype": "Password", "label": "Meta App Secret",
         "description": "Verifies X-Hub-Signature-256 on inbound WhatsApp webhooks. "
                        "Without it Baton refuses the webhook rather than trusting it."},
    ])

    frappe.db.commit()
    print("Phase 3 schema ready.")


def configure_gemini():
    """Set Google Gemini as the default model. Key added separately."""
    name = "Gemini"
    if frappe.db.exists("Baton AI Model", name):
        doc = frappe.get_doc("Baton AI Model", name)
    else:
        doc = frappe.new_doc("Baton AI Model")
        doc.model_name = name

    doc.provider = "Google Gemini"
    doc.model = "gemini-2.5-flash"
    doc.base_url = "https://generativelanguage.googleapis.com"
    doc.purpose = "General"
    doc.enabled = 1
    doc.is_default = 1
    doc.temperature = 0
    doc.max_tokens = 2048
    doc.timeout = 90
    doc.save(ignore_permissions=True)

    # Only one default.
    for other in frappe.get_all("Baton AI Model",
                                filters={"is_default": 1, "name": ["!=", doc.name]}, pluck="name"):
        frappe.db.set_value("Baton AI Model", other, "is_default", 0)

    frappe.db.commit()
    has_key = bool(doc.get_password("api_key", raise_exception=False))
    print(f"  + {doc.name} is default ({doc.model}) | api_key set: {has_key}")


def install_all():
    install()
    configure_gemini()
