"""Routes outgoing WhatsApp through OpenWA when it is enabled.

`WhatsApp Message.before_insert` calls `send_outgoing()`, which posts to
graph.facebook.com. With OpenWA configured we want the same row to go out
through the local bridge instead -- without editing the vendored app, so an
upgrade cannot quietly restore Meta dispatch.
"""

import frappe
from frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_message.whatsapp_message import (
    WhatsAppMessage,
)

from baton.channels import openwa


class BatonWhatsAppMessage(WhatsAppMessage):
    def set_whatsapp_account(self):
        # OpenWA needs no Meta account; only fall through when it is off.
        if openwa.is_enabled():
            return
        return super().set_whatsapp_account()

    def send_outgoing(self):
        if not openwa.is_enabled():
            return super().send_outgoing()

        if self.type != "Outgoing":
            return

        # A message the owner typed on their phone reached us via webhook. It is
        # already sent; dispatching would echo it back to the customer.
        if self.flags.get("baton_inbound_echo"):
            self.status = "Sent"
            return

        from baton.audit import log_action

        try:
            # CRM sets is_reply/reply_to_message_id; without passing it on,
            # a reply sends as an ordinary message and the quote is lost.
            resp = openwa.send_text(
                self.to, self.message,
                quoted_message_id=self.reply_to_message_id if self.is_reply else None,
            )
            self.message_id = (
                resp.get("id") or resp.get("messageId")
                or (resp.get("data") or {}).get("id")
            )
            self.status = "Sent"
            log_action("openwa.send", actor_type="AI_AGENT",
                       reference_doctype=self.reference_doctype,
                       reference_name=self.reference_name,
                       external_id=self.message_id,
                       output={"to": self.to, "chars": len(self.message or "")})
        except Exception as e:
            self.status = "Failed"
            log_action("openwa.send", status="Failed", actor_type="AI_AGENT",
                       reference_doctype=self.reference_doctype,
                       reference_name=self.reference_name,
                       error=str(e)[:500], output={"to": self.to})
            raise


def keep_baton_reference(doc, method=None):
    """Stop CRM re-filing a message Baton addressed deliberately.

    `crm.api.whatsapp.validate` resolves `reference_doctype`/`reference_name`
    from the phone number on every save, and prefers a Deal when the number
    matches both. That is right for an inbound message nobody has classified,
    and wrong for one we just sent as part of a run:

      * the run is parked on the Lead, and `resume_on_inbound` looks for a
        Waiting run on the record the message is filed against -- so the reply
        wakes nothing and the conversation stalls forever
      * `can_ai_send`, the turn cap and the rate limit all key on the same pair,
        so half the conversation is counted against one record and half against
        another
      * the audit trail stops answering "what did this run say, and to whom?"

    So a message Baton addressed keeps its address. Anything else -- an inbound
    message, one typed by a human -- is left to CRM to classify as it likes.

    Registered after CRM's hook (baton is installed last), which is what lets it
    put back what that hook overwrote.
    """
    wanted = doc.flags.get("baton_reference")
    if not wanted:
        return
    doctype, name = wanted
    if not doctype or not name:
        return
    if (doc.reference_doctype, doc.reference_name) != (doctype, name):
        doc.reference_doctype = doctype
        doc.reference_name = name
