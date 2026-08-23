"""Email author tagging and human-intervention detection.

Mirrors api/whatsapp.py exactly -- the same three-way author split, the same
state-machine hookup -- so a reply over email gets identical treatment to one
over WhatsApp. `baton_author` is set before insert so nothing can write a
Communication without it.

The one thing WhatsApp does not need and email does: telling an AI-sent email
apart from a human-sent one. WhatsApp Message rows are only ever written by
Baton or a human on the shared number, so "not claimed as AI" already means
"human". A Communication is Frappe's shared table for every outbound email
from every app, so an AI send has to flag itself explicitly -- see
`frappe.flags.baton_ai_email`, set immediately around the `frappe.sendmail`
call that sends on Baton's behalf.
"""

import frappe

from baton.conversation.state import mark_ai_sent, mark_human_intervention, mark_inbound


def tag_author(doc, method=None):
    if doc.get("communication_type") != "Communication":
        return
    if doc.get("baton_author"):
        return

    if doc.get("sent_or_received") == "Received":
        doc.baton_author = "contact"
    elif getattr(frappe.flags, "baton_ai_email", False):
        doc.baton_author = "ai"
    else:
        doc.baton_author = "human"


def on_communication(doc, method=None):
    """Drive the conversation state machine from every emailed Communication."""
    if doc.get("communication_type") != "Communication":
        return

    ref_dt, ref_dn = doc.get("reference_doctype"), doc.get("reference_name")
    if not (ref_dt and ref_dn):
        return

    author = doc.get("baton_author")

    if author == "contact":
        mark_inbound(ref_dt, ref_dn)

        from baton.conversation.parking import resume_on_inbound
        woke = resume_on_inbound(ref_dt, ref_dn, "Email", doc.name)

        if not woke:
            from baton.bots.runtime import start_inbound_bots
            start_inbound_bots(ref_dt, ref_dn, "Email", doc.name)

        from baton.conversation.state import cancel_pending_ai_actions
        cancel_pending_ai_actions(ref_dt, ref_dn, include_reply_waits=False)

        from baton.events import emit
        emit("lead.replied", reference_doctype=ref_dt, reference_name=ref_dn)
        emit("message.received", reference_doctype=ref_dt, reference_name=ref_dn)

        # Same re-scoring path WhatsApp replies already trigger -- qualification
        # is channel-agnostic, it just reads the merged transcript.
        if ref_dt == "CRM Lead":
            frappe.enqueue("baton.api.whatsapp.requalify", queue="long",
                           enqueue_after_commit=True, lead=ref_dn)

    elif author == "human":
        mark_human_intervention(ref_dt, ref_dn, reason="Human sent an email manually")

    elif author == "ai":
        mark_ai_sent(ref_dt, ref_dn)
        from baton.events import emit
        emit("message.sent", reference_doctype=ref_dt, reference_name=ref_dn)
