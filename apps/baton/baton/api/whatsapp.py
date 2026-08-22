"""WhatsApp author tagging and human-intervention detection.

`baton_author` is only worth having if nothing can write a message without it,
so it is set before insert rather than left to callers.
"""

import frappe

from baton.conversation.state import mark_ai_sent, mark_human_intervention, mark_inbound


def tag_author(doc, method=None):
    # The workflow engine and the agent set this explicitly; never overwrite.
    if doc.get("baton_author"):
        return

    if (doc.get("type") or "").lower() == "incoming":
        doc.baton_author = "contact"
    else:
        # Outgoing, and nobody claimed it as AI -> a person typed it.
        doc.baton_author = "human"


def on_message(doc, method=None):
    """Drive the conversation state machine from every WhatsApp message."""
    ref_dt, ref_dn = doc.get("reference_doctype"), doc.get("reference_name")
    if not (ref_dt and ref_dn):
        return

    author = doc.get("baton_author")

    if author == "contact":
        # The lead replied: reset the AI turn counter and withdraw queued
        # follow-ups, so we never send "just following up" after a reply.
        mark_inbound(ref_dt, ref_dn)

        # Wake whatever was parked waiting to hear from them, before anything
        # else touches the Waiting runs on this record.
        from baton.conversation.parking import resume_on_inbound
        woke = resume_on_inbound(ref_dt, ref_dn, "WhatsApp", doc.name)

        # Nothing was waiting for them, so nobody is mid-conversation. That is
        # the moment an inbound-triggered bot is for -- and only then, or it
        # would start a second bot on top of a conversation already running.
        if not woke:
            from baton.bots.runtime import start_inbound_bots
            start_inbound_bots(ref_dt, ref_dn, "WhatsApp", doc.name)

        # Withdraw queued follow-ups -- but not a conversation step that is
        # waiting for this exact message.
        from baton.conversation.state import cancel_pending_ai_actions
        cancel_pending_ai_actions(ref_dt, ref_dn, include_reply_waits=False)
        from baton.events import emit
        emit("lead.replied", reference_doctype=ref_dt, reference_name=ref_dn)
        emit("message.received", reference_doctype=ref_dt, reference_name=ref_dn)

        # Re-score on every inbound. Queued, never inline: an LLM call inside a
        # webhook request would block Meta's delivery (spec §43).
        if ref_dt == "CRM Lead":
            frappe.enqueue("baton.api.whatsapp.requalify", queue="long",
                           enqueue_after_commit=True, lead=ref_dn)

    elif author == "human":
        # A person sent manually on the shared number -> pause the AI.
        mark_human_intervention(ref_dt, ref_dn, reason="Human sent a WhatsApp message manually")

    elif author == "ai":
        mark_ai_sent(ref_dt, ref_dn)
        from baton.events import emit
        emit("message.sent", reference_doctype=ref_dt, reference_name=ref_dn)


def requalify(lead):
    """Re-score a lead after it replies, and convert if the band says so.

    Runs in the background queue. Failures are logged, never raised -- a lead
    replying must not fail because the model was unavailable.
    """
    from baton.audit import log_action

    try:
        if not frappe.db.exists("CRM Lead", lead):
            return
        if frappe.db.get_value("CRM Lead", lead, "converted"):
            return

        from baton.agents.qualification import qualify
        result = qualify("CRM Lead", lead)

        if result.next_action == "Create deal" and result.complete:
            from baton.agents.conversion import convert_assign_notify
            convert_assign_notify(lead)
    except Exception as e:
        log_action("lead.requalify", status="Failed", actor_type="AI_AGENT",
                   reference_doctype="CRM Lead", reference_name=lead,
                   error=str(e)[:600],
                   reason="Re-qualification after inbound message failed")
        frappe.log_error(title=f"Baton requalify failed for {lead}")
