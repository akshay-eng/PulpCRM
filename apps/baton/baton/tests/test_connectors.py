"""Connectors: one capability each, gated on a real connection.

Two things are being defended here. First, that granting a bot "comment on
records" does not also grant "reassign them" -- that was one checkbox before and
is five now. Second, that a bot never picks its own recipient: the model writes
the words, a person decides who they go to.
"""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from baton.bots import tools
from baton.bots.catalog import (BY_ID, availability, connector_available,
                                public_catalog, tools_for)

from .test_bot_runtime import _bot, _cleanup
from .test_engine import _lead


class TestConnectorsAreIndividual(FrappeTestCase):
    def test_the_grouped_connector_is_gone(self):
        self.assertIsNone(BY_ID.get("crm_operations"))

    def test_each_verb_is_its_own_connector(self):
        for cid in ("crm_assignment", "crm_comments", "crm_call_logging",
                    "crm_field_options", "crm_search"):
            self.assertIn(cid, BY_ID, f"{cid} should be a connector of its own")

    def test_granting_comments_does_not_grant_assignment(self):
        names = {t["name"] for t in tools_for({"crm_comments"})}
        self.assertIn("add_comment", names)
        self.assertNotIn("assign_to", names)

    def test_every_tool_still_belongs_to_exactly_one_connector(self):
        seen = {}
        for c in BY_ID.values():
            for t in c["tools"]:
                self.assertNotIn(t["name"], seen,
                                 f"{t['name']} is on both {seen.get(t['name'])} and {c['id']}")
                seen[t["name"]] = c["id"]

    def test_search_alone_can_see_nothing(self):
        """Search spans what the record connectors granted, not everything."""
        bot = _bot("T Bot SearchOnly", connectors=("crm_search",))
        ctx = {"bot": bot, "run": None, "doc": None, "vars": {}, "turn": 0}
        self.assertEqual(tools._allowed_doctypes(ctx), set())
        _cleanup()


class TestAvailability(FrappeTestCase):
    """A connector that needs an integration is unusable without one."""

    def test_connectors_with_no_integration_are_always_available(self):
        ok, why = connector_available(BY_ID["crm_leads"])
        self.assertTrue(ok)
        self.assertIsNone(why)

    def test_whatsapp_is_unavailable_when_nothing_is_connected(self):
        with patch("baton.bots.catalog._whatsapp_ready",
                   return_value=(False, "No WhatsApp account is Active.")):
            ok, why = connector_available(BY_ID["whatsapp"])
        self.assertFalse(ok)
        self.assertIn("not connected", why)

    def test_the_catalog_tells_the_builder_why(self):
        with patch("baton.bots.catalog._email_ready",
                   return_value=(False, "No outgoing email account is set up.")):
            entry = [c for c in public_catalog() if c["id"] == "email"][0]
        self.assertFalse(entry["available"])
        self.assertIn("No outgoing email account", entry["unavailable_reason"])

    def test_a_broken_check_reports_unavailable_rather_than_raising(self):
        with patch("baton.bots.catalog._whatsapp_ready", side_effect=RuntimeError("boom")):
            state = availability()
        self.assertFalse(state["whatsapp"]["ok"])

    def test_sending_refuses_when_the_channel_went_away(self):
        """A channel can be disconnected between one scheduled run and the next."""
        bot = _bot("T Bot Gone", connectors=("whatsapp",))
        run = frappe.get_doc({"doctype": "Baton Workflow Run", "bot": bot.name,
                              "status": "Running"}).insert(ignore_permissions=True)
        ctx = {"bot": bot, "run": run, "doc": None, "vars": {}, "turn": 0}
        with patch("baton.bots.catalog._whatsapp_ready", return_value=(False, "gone")):
            out = tools.execute("send_whatsapp", {"message": "hi"}, ctx)
        self.assertFalse(out["sent"])
        self.assertIn("not connected", out["refused"])
        _cleanup()


def _with_config(name, connector, cfg):
    bot = _bot(name, connectors=(connector,))
    bot.connectors[0].config = json.dumps(cfg)
    bot.save(ignore_permissions=True)
    frappe.db.commit()
    return bot


class TestRecipient(FrappeTestCase):
    """Who a message goes to is configuration, never a model's choice."""

    def setUp(self):
        self.run = frappe.get_doc({
            "doctype": "Baton Workflow Run", "status": "Running"}).insert(
            ignore_permissions=True)

    def tearDown(self):
        _cleanup()

    def _ctx(self, bot, doc=None):
        return {"bot": bot, "run": self.run, "doc": doc, "vars": {}, "turn": 0}

    def test_a_fixed_address_is_used_with_no_record_in_hand(self):
        bot = _with_config("T Bot Fixed", "email",
                           {"recipient_mode": "fixed", "recipient": "owner@example.com"})
        with patch("frappe.sendmail") as send:
            out = tools.execute("send_email", {"subject": "s", "body": "b"},
                                self._ctx(bot))
        self.assertTrue(out["sent"])
        self.assertEqual(send.call_args.kwargs["recipients"], ["owner@example.com"])

    def test_the_model_cannot_redirect_a_fixed_address(self):
        bot = _with_config("T Bot NoRedirect", "email",
                           {"recipient_mode": "fixed", "recipient": "owner@example.com"})
        with patch("frappe.sendmail") as send:
            tools.execute("send_email",
                          {"subject": "s", "body": "b", "to": "attacker@example.com"},
                          self._ctx(bot))
        self.assertEqual(send.call_args.kwargs["recipients"], ["owner@example.com"])

    def test_record_mode_uses_the_record(self):
        lead = _lead()
        frappe.db.set_value("CRM Lead", lead.name, "email", "buyer@example.com")
        lead.reload()
        bot = _with_config("T Bot Dyn", "email", {"recipient_mode": "record"})
        with patch("frappe.sendmail") as send, \
             patch("baton.conversation.state.can_ai_send", return_value=(True, "Auto", None)):
            tools.execute("send_email", {"subject": "s", "body": "b"},
                          self._ctx(bot, lead))
        self.assertEqual(send.call_args.kwargs["recipients"], ["buyer@example.com"])

    def test_a_named_field_overrides_the_usual_one(self):
        lead = _lead()
        frappe.db.set_value("CRM Lead", lead.name,
                            {"email": "primary@example.com",
                             "website": "secondary@example.com"})
        lead.reload()
        bot = _with_config("T Bot Field", "email",
                           {"recipient_mode": "record", "recipient_field": "website"})
        with patch("frappe.sendmail") as send, \
             patch("baton.conversation.state.can_ai_send", return_value=(True, "Auto", None)):
            tools.execute("send_email", {"subject": "s", "body": "b"},
                          self._ctx(bot, lead))
        self.assertEqual(send.call_args.kwargs["recipients"], ["secondary@example.com"])

    def test_fixed_mode_with_an_empty_box_refuses(self):
        bot = _with_config("T Bot Empty", "email", {"recipient_mode": "fixed"})
        with self.assertRaises(tools.ToolError):
            tools.execute("send_email", {"subject": "s", "body": "b"}, self._ctx(bot))

    def test_the_old_to_key_still_means_a_fixed_address(self):
        """Bots saved before the choice was explicit must keep working."""
        bot = _with_config("T Bot Legacy", "email", {"to": "legacy@example.com"})
        with patch("frappe.sendmail") as send:
            out = tools.execute("send_email", {"subject": "s", "body": "b"},
                                self._ctx(bot))
        self.assertTrue(out["sent"])
        self.assertEqual(send.call_args.kwargs["recipients"], ["legacy@example.com"])

    def test_whatsapp_honours_a_fixed_number(self):
        bot = _with_config("T Bot WaFixed", "whatsapp",
                           {"recipient_mode": "fixed", "recipient": "+919999999999"})
        with patch("baton.workflow.actions.whatsapp.send",
                   return_value={"sent": True}) as send, \
             patch("baton.bots.catalog._whatsapp_ready", return_value=(True, "OpenWA")):
            out = tools.execute("send_whatsapp", {"message": "hi"}, self._ctx(bot))
        self.assertTrue(out["sent"])
        self.assertEqual(send.call_args.kwargs["to"], "+919999999999")
        # A report to the owner carries no record, so it is not gated as if it
        # were a customer conversation.
        self.assertIsNone(send.call_args.kwargs["doc"])
