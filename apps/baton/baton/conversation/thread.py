"""One conversation view over two stores.

Email lives in Frappe's `Communication`; WhatsApp lives in `WhatsApp Message`.
Rather than copying both into a third table -- which would desynchronise from
the CRM timeline the moment anything wrote directly -- this reads from both and
normalises on the way out.

That keeps the Conversation Agent channel-agnostic (spec §65) without taking
ownership of message storage.
"""

import frappe
from frappe.utils import get_datetime

AUTHOR_LABEL = {"contact": "Customer", "human": "Sales rep", "ai": "Assistant"}

# Which doctype a message id belongs to, by channel -- the one thing every
# caller of an inbound-message id needs and would otherwise hardcode
# "WhatsApp Message" and quietly break the day a second channel exists.
MESSAGE_DOCTYPE = {"Email": "Communication", "WhatsApp": "WhatsApp Message"}


def message_text_and_time(channel, message_name):
    """(text, creation) for an inbound message id, resolved by channel.

    Returns (None, None) if the id does not exist -- a webhook redelivery or
    a race with a rolled-back insert, not something worth raising over.
    """
    doctype = MESSAGE_DOCTYPE.get(channel, "WhatsApp Message")
    content_field = "content" if doctype == "Communication" else "message"
    row = frappe.db.get_value(doctype, message_name, [content_field, "creation"], as_dict=True)
    if not row:
        return None, None
    return row.get(content_field), row.get("creation")


def _whatsapp_messages(reference_doctype, reference_name):
    if not frappe.db.exists("DocType", "WhatsApp Message"):
        return []

    rows = frappe.get_all(
        "WhatsApp Message",
        filters={"reference_doctype": reference_doctype, "reference_name": reference_name},
        fields=["name", "type", "message", "creation", "message_id", "status",
                "baton_author", "content_type"],
        order_by="creation asc",
    )
    out = []
    for r in rows:
        incoming = (r.type or "").lower() == "incoming"
        out.append({
            "channel": "WhatsApp",
            "direction": "incoming" if incoming else "outgoing",
            "author": r.baton_author or ("contact" if incoming else "human"),
            "content": r.message or "",
            "subject": None,
            "timestamp": get_datetime(r.creation),
            "external_id": r.message_id,
            "status": r.status,
            "doctype": "WhatsApp Message",
            "name": r.name,
        })
    return out


def _emails(reference_doctype, reference_name):
    rows = frappe.get_all(
        "Communication",
        filters={
            "reference_doctype": reference_doctype,
            "reference_name": reference_name,
            "communication_type": "Communication",
        },
        fields=["name", "sent_or_received", "content", "subject", "communication_date",
                "sender", "recipients"],
        order_by="communication_date asc",
    )
    out = []
    for r in rows:
        received = (r.sent_or_received or "") == "Received"
        out.append({
            "channel": "Email",
            "direction": "incoming" if received else "outgoing",
            # Frappe has no author column on Communication; outbound email from
            # Baton is logged separately in Baton Action Log.
            "author": "contact" if received else "human",
            "content": frappe.utils.strip_html(r.content or "")[:4000],
            "subject": r.subject,
            "timestamp": get_datetime(r.communication_date),
            "external_id": None,
            "status": None,
            "doctype": "Communication",
            "name": r.name,
        })
    return out


def get_conversation(reference_doctype, reference_name, limit=None):
    """All messages on a record, both channels, oldest first."""
    msgs = _whatsapp_messages(reference_doctype, reference_name) + _emails(
        reference_doctype, reference_name
    )
    msgs.sort(key=lambda m: m["timestamp"] or get_datetime("1900-01-01"))
    return msgs[-limit:] if limit else msgs


def last_inbound_at(reference_doctype, reference_name, channel=None):
    """When the contact last wrote. Drives the WhatsApp service window."""
    inbound = [
        m for m in get_conversation(reference_doctype, reference_name)
        if m["direction"] == "incoming" and (channel is None or m["channel"] == channel)
    ]
    return inbound[-1]["timestamp"] if inbound else None


def as_transcript(reference_doctype, reference_name, limit=40):
    """Render the conversation for an LLM prompt.

    Bounded on purpose: spec §12 forbids dumping the whole database into every
    call, and a long thread would crowd out the instruction.
    """
    lines = []
    for m in get_conversation(reference_doctype, reference_name, limit=limit):
        who = AUTHOR_LABEL.get(m["author"], m["author"])
        when = m["timestamp"].strftime("%d %b %H:%M") if m["timestamp"] else "?"
        prefix = f"[{when}] {who} ({m['channel']})"
        body = (m["content"] or "").strip().replace("\n", " ")[:600]
        if m["subject"]:
            body = f"{m['subject']}: {body}"
        lines.append(f"{prefix}: {body}")
    return "\n".join(lines) or "(no messages yet)"


@frappe.whitelist()
def get_thread(reference_doctype, reference_name):
    """Whitelisted read for the UI."""
    from baton.conversation.state import get_state

    frappe.has_permission(reference_doctype, "read", reference_name, throw=True)
    st = get_state(reference_doctype, reference_name, create=False)
    return {
        "messages": get_conversation(reference_doctype, reference_name),
        "state": st.state if st else "AI_ACTIVE",
        "paused_until": st.paused_until if st else None,
        "ai_turn_count": st.ai_turn_count if st else 0,
    }
