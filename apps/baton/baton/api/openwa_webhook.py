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
    contact = msg.get("contact") if isinstance(msg.get("contact"), dict) else {}
    return {
        "id": msg.get("id") or msg.get("messageId") or data.get("id"),
        "chat_id": chat_id,
        "text": (msg.get("body") or msg.get("text") or msg.get("caption") or ""),
        "from_me": bool(msg.get("fromMe") if msg.get("fromMe") is not None else data.get("fromMe")),
        "push_name": msg.get("pushName") or msg.get("notifyName") or contact.get("pushName"),
        "type": msg.get("type") or "chat",
        "media": msg.get("media") if isinstance(msg.get("media"), dict) else None,
    }


def _attach_media(doc, m):
    """Download the message's media and attach it to the WhatsApp Message.

    Returns the file URL, or None. Never raises: a media failure must not lose
    the message itself -- a picture that did not download is recoverable, a
    dropped customer message is not.
    """
    import mimetypes

    from baton.channels.openwa import MEDIA_CONTENT_TYPES, fetch_media

    try:
        blob = fetch_media(m["chat_id"], m["id"])
        if not blob:
            log_action("openwa.media_unavailable", status="Skipped", actor_type="CONNECTOR",
                       reference_doctype=doc.reference_doctype,
                       reference_name=doc.reference_name,
                       reason="OpenWA stored no media for this message "
                              "(archiving off, over the cap, or a URL-based send)",
                       output={"type": m["type"], "declared": m.get("media")})
            return None

        mimetype = (m.get("media") or {}).get("mimetype") or blob["mimetype"]
        ext = mimetypes.guess_extension(mimetype.split(";")[0]) or ".bin"
        short = str(m["id"])[-12:].replace("/", "_")

        f = frappe.get_doc({
            "doctype": "File",
            "file_name": f"whatsapp-{m['type']}-{short}{ext}",
            "content": blob["content"],
            "attached_to_doctype": "WhatsApp Message",
            "attached_to_name": doc.name,
            "is_private": 1,
        }).insert(ignore_permissions=True)

        doc.db_set("attach", f.file_url, update_modified=False)
        doc.db_set("content_type", MEDIA_CONTENT_TYPES.get(m["type"], "document"),
                   update_modified=False)
        log_action("openwa.media_saved", actor_type="CONNECTOR",
                   reference_doctype=doc.reference_doctype,
                   reference_name=doc.reference_name,
                   output={"file": f.file_url, "bytes": len(blob["content"]),
                           "mimetype": mimetype})
        return f.file_url
    except Exception as e:
        log_action("openwa.media_failed", status="Failed", actor_type="CONNECTOR",
                   reference_doctype=doc.reference_doctype,
                   reference_name=doc.reference_name, error=str(e)[:400])
        return None


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

    attached = _attach_media(doc, m) if m.get("media") else None

    if m.get("media") and not m["text"]:
        # Store the file path, matching frappe_whatsapp's convention for "no
        # caption". The CRM UI suppresses anything that looks like a file path,
        # so nothing is printed under the image.
        #
        # An empty string is NOT equivalent: CRM's reply composer renders on
        # `v-if="reply?.message"`, so an empty message makes Reply silently do
        # nothing on every uncaptioned image.
        doc.db_set("message", attached or f"[{m['type']}]", update_modified=False)

    return {"ok": True, "message": doc.name, "author": author,
            "reference": f"{doctype}/{name}", "media": attached}
