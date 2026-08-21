"""Inbound OpenWA events -> WhatsApp Message rows.

Everything Baton already does -- author tagging, the conversation thread, the
send gate, human-intervention pausing, the CRM WhatsApp tab -- keys off the
`WhatsApp Message` DocType. So this maps OpenWA events onto that same table
rather than introducing a parallel store. Nothing downstream needs to know which
bridge a message arrived through.
"""

import json

import frappe

from baton.audit import log_action
from baton.channels import openwa


def _match_lead(phone):
    """Find the CRM record this number belongs to."""
    if not phone:
        return None, None
    digits = phone.lstrip("+")
    tail = digits[-10:]  # match on the national part; prefixes vary in the wild

    for doctype, fields in (("CRM Lead", ["mobile_no", "phone"]),
                            ("CRM Deal", ["mobile_no"])):
        for field in fields:
            hit = frappe.db.sql(
                f"""SELECT name FROM `tab{doctype}`
                    WHERE `{field}` IS NOT NULL AND REPLACE(REPLACE(REPLACE(`{field}`,' ',''),'-',''),'+','')
                          LIKE %s ORDER BY modified DESC LIMIT 1""",
                (f"%{tail}",),
            )
            if hit:
                return doctype, hit[0][0]
    return None, None


def _extract(data):
    """Pull the fields we need out of an OpenWA message payload."""
    msg = data.get("message") if isinstance(data.get("message"), dict) else data
    chat_id = msg.get("chatId") or msg.get("from") or msg.get("to") or data.get("chatId")
    return {
        "id": msg.get("id") or msg.get("messageId") or data.get("id"),
        "chat_id": chat_id,
        "text": (msg.get("body") or msg.get("text") or msg.get("caption") or ""),
        "from_me": bool(msg.get("fromMe") if msg.get("fromMe") is not None else data.get("fromMe")),
        "push_name": msg.get("pushName") or msg.get("notifyName"),
        "type": msg.get("type") or "chat",
    }


@frappe.whitelist(allow_guest=True)
def inbound():
    """Signature-verified OpenWA webhook."""
    secret = frappe.get_cached_doc("Baton Settings").get_password(
        "openwa_webhook_secret", raise_exception=False
    )
    raw = frappe.request.get_data() or b""
    signature = frappe.get_request_header(openwa.SIGNATURE_HEADER)

    if not secret:
        # Fail closed, exactly as with the Meta webhook.
        frappe.throw("OpenWA webhook secret not configured.", frappe.PermissionError)

    if not openwa.verify_signature(raw, signature, secret):
        log_action("openwa.webhook_rejected", status="Failed", actor_type="SYSTEM",
                   decision="REJECTED", reason="X-OpenWA-Signature missing or invalid",
                   output={"had_signature": bool(signature), "bytes": len(raw),
                           "remote_addr": frappe.local.request_ip})
        frappe.db.commit()
        frappe.throw("Invalid webhook signature.", frappe.PermissionError)

    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except ValueError:
        return {"ok": False, "reason": "unparseable body"}

    event = payload.get("event") or payload.get("type") or ""
    data = payload.get("data") or payload.get("payload") or {}

    # Keep the raw shape once per event kind, so the mapping can be corrected
    # against reality rather than assumption.
    log_action(f"openwa.{event or 'unknown'}", actor_type="CONNECTOR",
               output={"raw": json.dumps(payload)[:3000]},
               reason="inbound OpenWA event")

    if event not in ("message.received", "message.sent"):
        return {"ok": True, "ignored": event}

    m = _extract(data)
    if not m["chat_id"]:
        return {"ok": True, "ignored": "no chat id"}
    if m["chat_id"].endswith("@g.us"):
        return {"ok": True, "ignored": "group chat"}

    # Dedup FIRST. Our own sends echo back as message.sent, and OpenWA retries
    # deliveries; both must be recognised as already-stored before we spend an
    # API call resolving the number, and before an echo can be logged as
    # "unmatched" and thrown away.
    if m["id"] and frappe.db.exists("WhatsApp Message", {"message_id": m["id"]}):
        return {"ok": True, "duplicate": m["id"]}

    # @lid chats carry no phone number in the payload, so ask OpenWA.
    phone = openwa.resolve_phone(m["chat_id"])
    doctype, name = _match_lead(phone)
    if not doctype:
        log_action("openwa.unmatched", actor_type="CONNECTOR",
                   reason=f"No CRM record for {phone or m['chat_id']}",
                   output={"chat_id": m["chat_id"], "resolved": phone,
                           "text": m["text"][:200]})
        return {"ok": True, "ignored": "no matching CRM record", "phone": phone}

    # THE DIFFERENTIATOR.
    #   inbound                     -> the contact
    #   outbound we sent            -> already recorded by the sender, skip
    #   outbound we did NOT send    -> a human typed it on their own phone
    if not m["from_me"]:
        author, kind = "contact", "Incoming"
    else:
        author, kind = "human", "Outgoing"

    doc = frappe.get_doc({
        "doctype": "WhatsApp Message",
        "type": kind,
        "message": m["text"],
        "content_type": "text",
        "to": phone,
        "message_id": m["id"],
        "profile_name": m["push_name"],
        "reference_doctype": doctype,
        "reference_name": name,
        "baton_author": author,
    })
    # Outgoing rows normally trigger a send; this one already happened on the
    # phone, so mark it as an echo and let the override skip dispatch.
    doc.flags.baton_inbound_echo = True
    doc.insert(ignore_permissions=True)
    frappe.db.commit()

    return {"ok": True, "message": doc.name, "author": author,
            "reference": f"{doctype}/{name}"}
