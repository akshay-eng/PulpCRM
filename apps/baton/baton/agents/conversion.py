"""Qualified lead -> Deal -> owner.

Everything here delegates to Frappe CRM's own machinery:

  * conversion  -> `crm.fcrm.doctype.crm_lead.crm_lead.convert_to_deal`, which
    already handles permissions, Contact, Organization and custom-field mapping
    by label+fieldtype. Reimplementing it would silently drop that mapping.
  * assignment  -> Frappe `Assignment Rule` (spec §22)
  * notification-> `CRM Notification`, so it lands in the existing bell UI

Baton's contribution is deciding *when*, and attaching the qualification brief.
"""

import frappe
from frappe.utils import cint, now_datetime

from baton.audit import already_done, log_action


def latest_result(lead):
    rows = frappe.get_all(
        "Baton Qualification Result",
        filters={"reference_doctype": "CRM Lead", "reference_name": lead},
        fields=["name", "score", "band", "summary", "next_action", "objections", "complete"],
        order_by="creation desc",
        limit_page_length=1,
    )
    return rows[0] if rows else None


def should_convert(lead, profile_name=None):
    """(bool, reason). Conversion requires a band whose action says so."""
    result = latest_result(lead)
    if not result:
        return False, "No qualification result yet"
    if not result.complete:
        return False, f"Qualification incomplete (score {result.score})"
    if result.next_action != "Create deal":
        return False, f"Band '{result.band}' says {result.next_action}, not conversion"
    if frappe.db.get_value("CRM Lead", lead, "converted"):
        return False, "Lead is already converted"
    return True, f"Band '{result.band}' at {result.score}/100"


def convert(lead, force=False):
    """Convert a qualified lead. Idempotent -- one deal per lead, ever."""
    from crm.fcrm.doctype.crm_lead.crm_lead import convert_to_deal

    key = f"convert:{lead}"
    if already_done(key):
        return None, "Already converted (idempotency)"

    if not force:
        ok, reason = should_convert(lead)
        if not ok:
            log_action("lead.convert", status="Skipped", actor_type="AI_AGENT",
                       reference_doctype="CRM Lead", reference_name=lead,
                       decision="NOT_CONVERTED", reason=reason)
            return None, reason

    result = latest_result(lead)
    deal_name = convert_to_deal(lead=lead)

    # Carry the qualification brief onto the deal's timeline so the owner sees
    # why the AI thought this was worth their time.
    if result and result.summary:
        frappe.get_doc({
            "doctype": "FCRM Note",
            "title": f"AI qualification — {result.band} ({result.score}/100)",
            "content": _brief(lead, result),
            "reference_doctype": "CRM Deal",
            "reference_docname": deal_name,
        }).insert(ignore_permissions=True)

    log_action("lead.convert", actor_type="AI_AGENT",
               reference_doctype="CRM Lead", reference_name=lead,
               idempotency_key=key, external_id=deal_name,
               decision="CONVERTED",
               reason=f"score {result.score if result else '?'} -> deal {deal_name}",
               output={"deal": deal_name})

    from baton.events import emit
    emit("deal.created", reference_doctype="CRM Deal", reference_name=deal_name)

    frappe.db.commit()
    return deal_name, "Converted"


def _brief(lead, result):
    """The §113 handoff brief -- what a salesperson needs before calling."""
    doc = frappe.get_doc("CRM Lead", lead)
    parts = [
        f"<b>Score</b>: {result.score}/100 ({result.band})",
        f"<b>Summary</b>: {result.summary or '—'}",
    ]
    if result.objections:
        parts.append(f"<b>Objections</b>: {result.objections}")
    if doc.get("mobile_no"):
        parts.append(f"<b>Phone</b>: {doc.mobile_no}")
    if doc.get("email"):
        parts.append(f"<b>Email</b>: {doc.email}")
    parts.append("<b>Recommended</b>: contact within 24 hours.")
    return "<br>".join(parts)


def assign(deal):
    """Hand the deal to Frappe's own Assignment Rule engine."""
    rule = frappe.db.get_value(
        "Assignment Rule",
        {"document_type": "CRM Deal", "disabled": 0},
        "name",
    )
    if not rule:
        return None, "No Assignment Rule configured for CRM Deal"

    doc = frappe.get_doc("CRM Deal", deal)

    # apply_assign() evaluates assign_condition via eval(), whose locals must be
    # a mapping -- a Document is not one. Frappe catches the resulting TypeError
    # and returns False, so passing the Document makes assignment silently do
    # nothing. as_dict() is required, not stylistic.
    applied = frappe.get_doc("Assignment Rule", rule).apply_assign(doc.as_dict())

    user = _assigned_user(deal)
    status = "ASSIGNED" if user else "NOT_ASSIGNED"
    log_action("deal.assign", actor_type="SYSTEM",
               reference_doctype="CRM Deal", reference_name=deal,
               decision=status,
               reason=f"via Assignment Rule '{rule}' (applied={bool(applied)})",
               output={"user": user})
    if not user:
        return None, f"Rule '{rule}' matched nobody"
    return user, f"Assigned via '{rule}'"


def _assigned_user(deal):
    """Read the current assignee from Frappe's _assign field."""
    raw = frappe.db.get_value("CRM Deal", deal, "_assign")
    if not raw:
        return None
    try:
        import json
        users = json.loads(raw)
        return users[0] if users else None
    except (ValueError, TypeError):
        return None


def notify_owner(deal, user=None):
    """Owner notification through the existing CRM bell (spec §23)."""
    doc = frappe.get_doc("CRM Deal", deal)
    owner = user or _assigned_user(deal) or doc.get("deal_owner")
    if not owner:
        return None, "No owner to notify"

    key = f"notify:{deal}:{owner}"
    if already_done(key):
        return None, "Already notified"

    result = latest_result(doc.get("lead")) if doc.get("lead") else None
    headline = f"New qualified deal: {doc.get('organization') or deal}"
    if result:
        headline += f" — {result.score}/100 ({result.band})"

    frappe.get_doc({
        "doctype": "CRM Notification",
        "from_user": frappe.session.user,
        "to_user": owner,
        "type": "Mention",
        "message": headline,
        "notification_text": headline,
        "reference_doctype": "CRM Deal",
        "reference_name": deal,
    }).insert(ignore_permissions=True)

    log_action("deal.notify_owner", actor_type="SYSTEM",
               reference_doctype="CRM Deal", reference_name=deal,
               idempotency_key=key, decision="NOTIFIED",
               reason=headline, output={"user": owner})
    frappe.db.commit()
    return owner, "Notified"


def convert_assign_notify(lead, force=False):
    """The whole Phase 4 path, in order, each step logged."""
    deal, reason = convert(lead, force=force)
    if not deal:
        return {"converted": False, "reason": reason}

    user, assign_reason = assign(deal)
    notified, notify_reason = notify_owner(deal, user)

    return {
        "converted": True, "deal": deal,
        "assigned_to": user, "assignment": assign_reason,
        "notified": notified, "notification": notify_reason,
    }
