"""Operator helpers — send a WhatsApp message to a number from the CRM.

Exists because "message this number" is the thing you actually do while setting
a deployment up, and doing it by hand means re-deriving lead lookup, the send
gate and channel routing every time.
"""

import frappe

from baton.channels import openwa
from baton.conversation.state import can_ai_send


def _lead_for(number):
    """Find or create the CRM Lead this number belongs to."""
    tail = "".join(c for c in str(number) if c.isdigit())[-10:]
    hit = frappe.db.sql(
        """SELECT name FROM `tabCRM Lead`
           WHERE REPLACE(REPLACE(REPLACE(mobile_no,' ',''),'-',''),'+','') LIKE %s
           ORDER BY modified DESC LIMIT 1""",
        (f"%{tail}",),
    )
    if hit:
        return frappe.get_doc("CRM Lead", hit[0][0]), False

    normalised = openwa.from_chat_id(openwa.to_chat_id(number))
    lead = frappe.get_doc({
        "doctype": "CRM Lead",
        "first_name": "WhatsApp",
        "last_name": normalised or str(number),
        "lead_name": f"WhatsApp {normalised or number}",
        "mobile_no": normalised or str(number),
    }).insert(ignore_permissions=True)
    frappe.db.commit()
    return lead, True


@frappe.whitelist()
def send_whatsapp(number, text, author="ai", override_quiet_hours=False):
    """Send `text` to `number`, creating the Lead if it does not exist.

    `override_quiet_hours` is explicit and defaults off: quiet hours exist to
    stop the system messaging people at night, and bypassing them should be a
    decision someone made, not a default.
    """
    frappe.only_for(["System Manager", "Sales Manager"])

    lead, created = _lead_for(number)
    allowed, mode, why = can_ai_send("CRM Lead", lead.name, channel="WhatsApp")

    settings = frappe.get_single("Baton Settings")
    restore = None
    if not allowed and override_quiet_hours and "Quiet hours" in why:
        restore = settings.quiet_hours_enabled
        settings.quiet_hours_enabled = 0
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.clear_cache(doctype="Baton Settings")
        allowed, mode, why = can_ai_send("CRM Lead", lead.name, channel="WhatsApp")

    try:
        if not allowed:
            return {"sent": False, "lead": lead.name, "reason": why}

        msg = frappe.get_doc({
            "doctype": "WhatsApp Message", "type": "Outgoing",
            "message": text, "content_type": "text",
            "to": lead.mobile_no,
            "reference_doctype": "CRM Lead", "reference_name": lead.name,
            "baton_author": author,
        }).insert(ignore_permissions=True)
        frappe.db.commit()
        msg.reload()
        return {
            "sent": msg.status == "Sent", "message": msg.name, "status": msg.status,
            "wa_id": msg.message_id, "lead": lead.name, "lead_created": created,
            "routed_to": f"{msg.reference_doctype}/{msg.reference_name}",
            "gate": why, "mode": mode,
        }
    finally:
        if restore is not None:
            s = frappe.get_single("Baton Settings")
            s.quiet_hours_enabled = restore
            s.save(ignore_permissions=True)
            frappe.db.commit()
            frappe.clear_cache(doctype="Baton Settings")
