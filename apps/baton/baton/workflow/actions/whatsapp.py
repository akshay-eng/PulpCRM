"""The one path an AI-authored WhatsApp message can take out of Baton.

Both the `Send WhatsApp` node and the `AI Conversation` node call `send()`.
That is deliberate and load-bearing: `conversation.state` promises there is no
second route to sending, and every guarantee built on `can_ai_send` -- human
handoff, quiet hours, turn caps, do-not-contact -- depends on it staying true.

Extracted from engine._send_whatsapp so a second caller could not become a
second copy.
"""

import json

import frappe

from baton.audit import already_done, log_action
from baton.conversation.state import can_ai_send
from baton.conversation.whatsapp_policy import choose_send_mode


def send(*, to, message, run, node, doc=None, author="ai", template=None, turn=0):
    """Send, draft, or refuse. Returns an outcome dict for the run step.

    Never raises for a refusal -- a blocked send is a normal outcome that has to
    be recorded, not an error that fails the run.
    """
    if "frappe_whatsapp" not in frappe.get_installed_apps():
        return {"skipped": "frappe_whatsapp not installed"}

    to = to or (doc.get("mobile_no") if doc else None)
    if not to:
        return {"skipped": "no recipient"}

    if not (message or "").strip():
        return {"skipped": "nothing to send"}

    # The turn suffix matters: a conversation node re-enters itself, and without
    # it the second send collides with the first and is silently dropped.
    key = f"whatsapp:{run.name}:{node.node_id}:{turn}"
    if already_done(key):
        return {"skipped": "already sent (idempotency)"}

    ref_dt = doc.doctype if doc else None
    ref_dn = doc.name if doc else None

    if author == "ai" and doc:
        allowed, mode, why = can_ai_send(ref_dt, ref_dn, channel="WhatsApp")
        if not allowed:
            log_action("whatsapp.send", status="Skipped", actor_type="AI_AGENT",
                       reference_doctype=ref_dt, reference_name=ref_dn,
                       workflow_run=run.name, node_id=node.node_id,
                       decision="SUPPRESSED", reason=why)
            return {"skipped": why, "blocked": True}

        # Meta only accepts free-form text inside 24 hours of the contact's last
        # message. Outside it, an untemplated send is rejected at the API and the
        # customer simply never hears from us -- so refuse here, visibly, rather
        # than writing a message that cannot be delivered.
        policy = choose_send_mode(ref_dt, ref_dn, template=template)
        if policy.get("mode") == "blocked":
            log_action("whatsapp.send", status="Skipped", actor_type="AI_AGENT",
                       reference_doctype=ref_dt, reference_name=ref_dn,
                       workflow_run=run.name, node_id=node.node_id,
                       decision="SUPPRESSED", reason=policy.get("reason"))
            return {"skipped": policy.get("reason"), "blocked": True}

        if mode == "Draft":
            approval = frappe.get_doc({
                "doctype": "Baton Approval",
                "kind": "Send Message",
                "status": "Pending",
                "draft_text": message,
                "reference_doctype": ref_dt,
                "reference_name": ref_dn,
                "workflow_run": run.name,
                "payload": json.dumps({"to": to, "channel": "WhatsApp"}, default=str),
            }).insert(ignore_permissions=True)
            log_action("whatsapp.draft", actor_type="AI_AGENT",
                       reference_doctype=ref_dt, reference_name=ref_dn,
                       workflow_run=run.name, node_id=node.node_id,
                       decision="AWAIT_APPROVAL", reason="Draft mode is on for WhatsApp",
                       output={"approval": approval.name})
            return {"drafted": approval.name, "to": to}

    msg = frappe.get_doc({
        "doctype": "WhatsApp Message",
        "type": "Outgoing",
        "to": to,
        "message": message,
        "content_type": "text",
        "reference_doctype": ref_dt,
        "reference_name": ref_dn,
        # Who wrote this is a column, not a system: it is what lets a human
        # reply pause the AI on this conversation.
        "baton_author": author,
    })
    # CRM's own validate hook re-resolves the reference from the phone number
    # and would move this message onto whichever record it likes -- breaking the
    # park this run is about to make. See overrides.whatsapp_message.
    msg.flags.baton_reference = (ref_dt, ref_dn)
    msg.insert(ignore_permissions=True)

    log_action("whatsapp.send", actor_type="AI_AGENT",
               reference_doctype=ref_dt, reference_name=ref_dn,
               workflow_run=run.name, node_id=node.node_id,
               idempotency_key=key, external_id=msg.name, output={"to": to})
    return {"whatsapp_message": msg.name, "to": to, "sent": True}
