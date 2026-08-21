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
            resp = openwa.send_text(self.to, self.message)
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
