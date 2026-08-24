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

import re

import frappe

from baton.conversation.state import mark_ai_sent, mark_human_intervention, mark_inbound

# Standard "nobody reads replies to this" senders: a bounce or a service
# notification, never a prospect. crm.utils.create_lead_from_incoming_email
# has no sender filter at all, so every one of these becomes a real CRM Lead
# named after its subject line unless something stops it first.
_AUTOMATED_SENDER = re.compile(
    r"^(mailer[-_.]?daemon|postmaster|no[-_.]?reply|do[-_.]?not[-_.]?reply|"
    r"bounces?|mail[-_.]?daemon)@",
    re.IGNORECASE,
)


def _looks_automated(sender):
    return bool(sender and _AUTOMATED_SENDER.match(sender))


def _remove_junk_lead(sender):
    """crm's after_insert hook on Communication runs before this one (crm
    installs before baton), so the Lead already exists by the time we get
    here -- the fix is to undo the create, not to prevent it.

    Only touches a Lead created in the last couple of minutes: an old lead
    that happens to share this address is somebody's actual data, not
    something this email just caused, and must not be swept up with it.
    """
    row = frappe.db.get_value(
        "CRM Lead", {"email": sender}, ["name", "creation"],
        order_by="creation desc", as_dict=True,
    )
    if not row:
        return
    age = (frappe.utils.now_datetime() - frappe.utils.get_datetime(row.creation)).total_seconds()
    if age > 120:
        return
    frappe.delete_doc("CRM Lead", row.name, force=True, ignore_permissions=True,
                      delete_permanently=True)


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

    if doc.get("sent_or_received") == "Received" and _looks_automated(doc.get("sender")):
        _remove_junk_lead(doc.get("sender"))
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
