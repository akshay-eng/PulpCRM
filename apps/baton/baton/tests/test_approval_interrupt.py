"""Stopping to ask a person.

The failure that matters here is silent permission: an approval that nobody
answered, or that failed to send, must never end up meaning "yes". Every test
below is a way that could happen.
"""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from baton.bots import approval, runtime, tools

from .test_bot_runtime import _bot, _cleanup, _replies
from .test_engine import _lead


def _guarded(name="T Bot Guard", channel="Email", to="boss@example.com",
             gated="send_whatsapp", **kw):
    return _bot(name, connectors=("crm_leads", "whatsapp"),
                approval_channel=channel, approval_recipient=to,
                gated_tools=gated, approval_timeout_hours=24, **kw)


def _pending(bot):
    rows = frappe.get_all("Baton Approval", filters={"bot": bot.name},
                          fields=["name"], order_by="creation desc")
    return frappe.get_doc("Baton Approval", rows[0].name) if rows else None


class TestWhichToolsAreGuarded(FrappeTestCase):
    def tearDown(self):
        _cleanup()

    def test_nothing_is_guarded_when_the_channel_is_off(self):
        bot = _guarded("T Bot Off", channel="Off")
        self.assertEqual(approval.gated(bot), set())

    def test_tools_are_read_one_per_line(self):
        bot = _guarded("T Bot Lines", gated="send_whatsapp\nsend_email")
        self.assertEqual(approval.gated(bot), {"send_whatsapp", "send_email"})

    def test_commas_work_too(self):
        bot = _guarded("T Bot Commas", gated="send_whatsapp, assign_to")
        self.assertEqual(approval.gated(bot), {"send_whatsapp", "assign_to"})


class TestTheInterrupt(FrappeTestCase):
    def setUp(self):
        self.lead = _lead()

    def tearDown(self):
        _cleanup()

    def test_a_guarded_tool_parks_the_run_instead_of_running(self):
        bot = _guarded("T Bot Parks")
        script = _replies({"tool": "send_whatsapp", "args": {"message": "hello"},
                           "done": False})
        with patch("baton.bots.runtime.chat_json", side_effect=script), \
             patch("frappe.sendmail") as send, \
             patch("baton.workflow.actions.whatsapp.send") as wa:
            run = runtime.run_bot(bot.name, doc=self.lead)

        doc = frappe.get_doc("Baton Workflow Run", run)
        self.assertEqual(doc.status, "Waiting")
        self.assertEqual(doc.waiting_for, "Approval")
        # The whole point: the guarded action did not happen.
        wa.assert_not_called()
        # And a person was actually asked.
        send.assert_called_once()

    def test_the_email_carries_both_choices(self):
        bot = _guarded("T Bot Links")
        script = _replies({"tool": "send_whatsapp", "args": {"message": "hi"},
                           "done": False})
        with patch("baton.bots.runtime.chat_json", side_effect=script), \
             patch("frappe.sendmail") as send, \
             patch("baton.workflow.actions.whatsapp.send"):
            runtime.run_bot(bot.name, doc=self.lead)

        body = send.call_args.kwargs["message"]
        self.assertIn("decision=Approved", body)
        self.assertIn("decision=Rejected", body)
        self.assertIn(_pending(bot).token, body)

    def test_the_message_being_approved_is_shown_to_the_human(self):
        bot = _guarded("T Bot Shows")
        script = _replies({"tool": "send_whatsapp",
                           "args": {"message": "Are you free Thursday?"}, "done": False})
        with patch("baton.bots.runtime.chat_json", side_effect=script), \
             patch("frappe.sendmail"), patch("baton.workflow.actions.whatsapp.send"):
            runtime.run_bot(bot.name, doc=self.lead)
        self.assertIn("Are you free Thursday?", _pending(bot).draft_text)

    def test_a_delivery_failure_does_not_become_permission(self):
        """If the question never went out, the answer is still not yes."""
        bot = _guarded("T Bot Undelivered")
        script = _replies({"tool": "send_whatsapp", "args": {"message": "hi"},
                           "done": False})
        with patch("baton.bots.runtime.chat_json", side_effect=script), \
             patch("frappe.sendmail", side_effect=RuntimeError("smtp down")), \
             patch("baton.workflow.actions.whatsapp.send") as wa:
            run = runtime.run_bot(bot.name, doc=self.lead)

        self.assertEqual(frappe.db.get_value("Baton Workflow Run", run, "status"), "Waiting")
        self.assertEqual(_pending(bot).status, "Pending")
        wa.assert_not_called()

    def test_an_unguarded_tool_is_not_interrupted(self):
        bot = _guarded("T Bot Free", gated="send_email")
        script = _replies({"tool": "send_whatsapp", "args": {"message": "hi"},
                           "done": False},
                          {"done": True, "summary": "sent"})
        with patch("baton.bots.runtime.chat_json", side_effect=script), \
             patch("baton.workflow.actions.whatsapp.send",
                   return_value={"sent": True}) as wa, \
             patch("baton.bots.catalog._whatsapp_ready", return_value=(True, "OpenWA")), \
             patch("baton.channels.openwa.is_enabled", return_value=True):
            runtime.run_bot(bot.name, doc=self.lead)
        wa.assert_called_once()


class TestTheAnswer(FrappeTestCase):
    def setUp(self):
        self.lead = _lead()
        self.bot = _guarded("T Bot Answer")
        script = _replies({"tool": "send_whatsapp", "args": {"message": "hello"},
                           "done": False})
        with patch("baton.bots.runtime.chat_json", side_effect=script), \
             patch("frappe.sendmail"), patch("baton.workflow.actions.whatsapp.send"):
            self.run = runtime.run_bot(self.bot.name, doc=self.lead)
        self.approval = _pending(self.bot)

    def tearDown(self):
        _cleanup()

    def test_approving_runs_the_action_that_was_approved(self):
        approval.resolve(self.approval, "Approved", by="test")
        script = _replies({"done": True, "summary": "done"})
        with patch("baton.bots.runtime.chat_json", side_effect=script), \
             patch("baton.workflow.actions.whatsapp.send",
                   return_value={"sent": True}) as wa, \
             patch("baton.bots.catalog._whatsapp_ready", return_value=(True, "OpenWA")), \
             patch("baton.channels.openwa.is_enabled", return_value=True):
            runtime.run_bot(self.bot.name, resume_run=self.run, run_reason="approval")

        wa.assert_called_once()
        self.assertEqual(wa.call_args.kwargs["message"], "hello")

    def test_rejecting_does_not_run_it(self):
        approval.resolve(self.approval, "Rejected", by="test")
        script = _replies({"done": True, "summary": "gave up"})
        with patch("baton.bots.runtime.chat_json", side_effect=script), \
             patch("baton.workflow.actions.whatsapp.send") as wa:
            runtime.run_bot(self.bot.name, resume_run=self.run, run_reason="approval")
        wa.assert_not_called()

    def test_the_model_is_told_it_was_rejected(self):
        approval.resolve(self.approval, "Rejected", by="test")
        seen = {}

        def spy(messages, **kw):
            seen["text"] = messages[-1]["content"]
            return {"done": True, "summary": "ok"}

        with patch("baton.bots.runtime.chat_json", side_effect=spy), \
             patch("baton.workflow.actions.whatsapp.send"):
            runtime.run_bot(self.bot.name, resume_run=self.run, run_reason="approval")
        self.assertIn("rejected", seen["text"].lower())

    def test_a_deadline_that_passes_is_not_a_yes(self):
        """Nobody answered. That is not permission."""
        script = _replies({"done": True, "summary": "timed out"})
        with patch("baton.bots.runtime.chat_json", side_effect=script), \
             patch("baton.workflow.actions.whatsapp.send") as wa:
            runtime.run_bot(self.bot.name, resume_run=self.run, run_reason="timeout")
        wa.assert_not_called()
        self.assertEqual(
            frappe.db.get_value("Baton Approval", self.approval.name, "status"), "Expired")

    def test_answering_twice_changes_nothing(self):
        approval.resolve(self.approval, "Approved", by="test")
        self.approval.reload()
        out = approval.resolve(self.approval, "Rejected", by="test")
        self.assertFalse(out["ok"])
        self.assertEqual(
            frappe.db.get_value("Baton Approval", self.approval.name, "status"), "Approved")


class TestWhatsAppReplies(FrappeTestCase):
    def test_yes_and_a_code_are_understood(self):
        self.assertEqual(approval.parse_reply("YES 4KDP"), ("Approved", "4KDP"))
        self.assertEqual(approval.parse_reply("no 4KDP"), ("Rejected", "4KDP"))

    def test_natural_wording_is_understood(self):
        self.assertEqual(approval.parse_reply("approve 4KDP")[0], "Approved")
        self.assertEqual(approval.parse_reply("stop 4KDP")[0], "Rejected")

    def test_an_ordinary_message_is_not_an_answer(self):
        self.assertEqual(approval.parse_reply("sounds good, call me tomorrow"),
                         (None, None))
        self.assertEqual(approval.parse_reply(""), (None, None))

    def test_a_bare_yes_carries_no_code(self):
        self.assertEqual(approval.parse_reply("yes"), ("Approved", None))


class TestOnlyTheRightPersonCanAnswer(FrappeTestCase):
    def tearDown(self):
        _cleanup()

    def test_a_reply_from_another_number_is_ignored(self):
        """A lead saying "no" must not reject their own manager's approval."""
        bot = _guarded("T Bot Wrong", channel="WhatsApp", to="+919000000001")
        appr = frappe.get_doc({
            "doctype": "Baton Approval", "status": "Pending", "kind": "Send Message",
            "code": "4KDP", "token": "t", "bot": bot.name, "channel": "WhatsApp",
            "sent_to": "+919000000001", "tool_name": "send_whatsapp",
            "payload": json.dumps({"tool": "send_whatsapp", "args": {}}),
        }).insert(ignore_permissions=True)

        msg = frappe._dict({"message": "NO 4KDP", "from": "+919000000002"})
        self.assertFalse(approval.try_reply(msg))
        self.assertEqual(frappe.db.get_value("Baton Approval", appr.name, "status"),
                         "Pending")

    def test_a_reply_from_the_right_number_resolves_it(self):
        bot = _guarded("T Bot Right", channel="WhatsApp", to="+919000000001")
        appr = frappe.get_doc({
            "doctype": "Baton Approval", "status": "Pending", "kind": "Send Message",
            "code": "7XQM", "token": "t", "bot": bot.name, "channel": "WhatsApp",
            "sent_to": "+919000000001", "tool_name": "send_whatsapp",
            "payload": json.dumps({"tool": "send_whatsapp", "args": {}}),
        }).insert(ignore_permissions=True)

        msg = frappe._dict({"message": "YES 7XQM", "from": "919000000001"})
        with patch("baton.channels.openwa.send_text"):
            self.assertTrue(approval.try_reply(msg))
        self.assertEqual(frappe.db.get_value("Baton Approval", appr.name, "status"),
                         "Approved")


class TestTheEmailLink(FrappeTestCase):
    def setUp(self):
        self.bot = _guarded("T Bot Link")
        self.appr = frappe.get_doc({
            "doctype": "Baton Approval", "status": "Pending", "kind": "Send Message",
            "code": "9ZZP", "token": "s3cret-token", "bot": self.bot.name,
            "channel": "Email", "sent_to": "boss@example.com",
            "tool_name": "send_whatsapp",
            "expires_at": add_to_date(now_datetime(), hours=4),
            "payload": json.dumps({"tool": "send_whatsapp", "args": {}}),
        }).insert(ignore_permissions=True)

    def tearDown(self):
        _cleanup()

    def test_a_wrong_token_decides_nothing(self):
        from baton.api import approve

        with patch("frappe.respond_as_web_page"):
            approve.decide(code="9ZZP", decision="Approved", token="guessed")
        self.assertEqual(frappe.db.get_value("Baton Approval", self.appr.name, "status"),
                         "Pending")

    def test_the_right_token_approves(self):
        from baton.api import approve

        with patch("frappe.respond_as_web_page"):
            approve.decide(code="9ZZP", decision="Approved", token="s3cret-token")
        self.assertEqual(frappe.db.get_value("Baton Approval", self.appr.name, "status"),
                         "Approved")

    def test_an_expired_link_does_nothing(self):
        from baton.api import approve

        frappe.db.set_value("Baton Approval", self.appr.name, "expires_at",
                            add_to_date(now_datetime(), hours=-1))
        with patch("frappe.respond_as_web_page"):
            approve.decide(code="9ZZP", decision="Approved", token="s3cret-token")
        self.assertEqual(frappe.db.get_value("Baton Approval", self.appr.name, "status"),
                         "Expired")

    def test_a_nonsense_decision_is_refused(self):
        from baton.api import approve

        with patch("frappe.respond_as_web_page"):
            approve.decide(code="9ZZP", decision="Maybe", token="s3cret-token")
        self.assertEqual(frappe.db.get_value("Baton Approval", self.appr.name, "status"),
                         "Pending")


class TestDraftModeApprovalActuallyResumes(FrappeTestCase):
    """A bot's own send_whatsapp/send_email, drafted because the global send
    mode is Draft (not because the tool was gated), used to return a plain
    dict -- so the run never parked, and a human approving the draft later
    had nothing waiting to resume. The message never actually went out."""

    def setUp(self):
        from .test_handoff import _settings, _snapshot_settings

        self._before = _snapshot_settings()
        _settings(ai_enabled=1, whatsapp_send_mode="Draft", email_send_mode="Draft",
                 quiet_hours_enabled=0, max_messages_per_lead_per_day=0)
        self.lead = _lead()
        self.bot = _bot("T Bot Drafter", connectors=("crm_leads", "whatsapp", "email"),
                        channel="Any")

    def tearDown(self):
        from .test_handoff import _settings

        _settings(**self._before)
        _cleanup()

    def test_a_drafted_whatsapp_message_parks_with_the_right_payload(self):
        script = _replies({"tool": "send_whatsapp", "args": {"message": "hello there"},
                           "done": False})
        with patch("baton.bots.runtime.chat_json", side_effect=script), \
             patch("baton.bots.catalog._whatsapp_ready", return_value=(True, "OpenWA")), \
             patch("baton.channels.openwa.is_enabled", return_value=True):
            run = runtime.run_bot(self.bot.name, doc=self.lead)

        doc = frappe.get_doc("Baton Workflow Run", run)
        self.assertEqual(doc.status, "Waiting")
        self.assertEqual(doc.waiting_for, "Approval")

        appr = _pending(self.bot) or frappe.get_doc("Baton Approval", frappe.get_all(
            "Baton Approval", filters={"reference_name": self.lead.name},
            order_by="creation desc", limit_page_length=1)[0].name)
        payload = json.loads(appr.payload)
        self.assertEqual(payload["tool"], "send_whatsapp")
        self.assertEqual(payload["args"]["message"], "hello there")

    def test_approving_a_drafted_whatsapp_message_actually_sends_it(self):
        script = _replies({"tool": "send_whatsapp", "args": {"message": "hello there"},
                           "done": False})
        with patch("baton.bots.runtime.chat_json", side_effect=script), \
             patch("baton.bots.catalog._whatsapp_ready", return_value=(True, "OpenWA")), \
             patch("baton.channels.openwa.is_enabled", return_value=True):
            run = runtime.run_bot(self.bot.name, doc=self.lead)

        appr = frappe.get_doc("Baton Approval", frappe.get_all(
            "Baton Approval", filters={"reference_name": self.lead.name},
            order_by="creation desc", limit_page_length=1)[0].name)
        approval.resolve(appr, "Approved", by="test")

        resume_script = _replies({"done": True, "summary": "sent"})
        with patch("baton.bots.runtime.chat_json", side_effect=resume_script), \
             patch("baton.bots.catalog._whatsapp_ready", return_value=(True, "OpenWA")), \
             patch("baton.workflow.actions.whatsapp.send",
                   return_value={"sent": True}) as wa:
            runtime.run_bot(self.bot.name, resume_run=run, run_reason="approval")

        wa.assert_called_once()
        self.assertEqual(wa.call_args.kwargs["message"], "hello there"[:900])
        self.assertTrue(wa.call_args.kwargs["skip_draft"])

    def test_approving_a_drafted_email_actually_sends_it(self):
        self.lead.db_set("email", "lead@example.com")
        script = _replies({"tool": "send_email",
                           "args": {"subject": "Following up", "body": "hi there"},
                           "done": False})
        with patch("baton.bots.runtime.chat_json", side_effect=script):
            run = runtime.run_bot(self.bot.name, doc=self.lead)

        appr = frappe.get_doc("Baton Approval", frappe.get_all(
            "Baton Approval", filters={"reference_name": self.lead.name},
            order_by="creation desc", limit_page_length=1)[0].name)
        payload = json.loads(appr.payload)
        self.assertEqual(payload["tool"], "send_email")
        approval.resolve(appr, "Approved", by="test")

        resume_script = _replies({"done": True, "summary": "sent"})
        with patch("baton.bots.runtime.chat_json", side_effect=resume_script), \
             patch("frappe.sendmail") as sendmail:
            runtime.run_bot(self.bot.name, resume_run=run, run_reason="approval")

        sendmail.assert_called_once()
        self.assertEqual(sendmail.call_args.kwargs["recipients"], ["lead@example.com"])

    def test_rejecting_a_drafted_message_never_sends_it(self):
        script = _replies({"tool": "send_whatsapp", "args": {"message": "hello there"},
                           "done": False})
        with patch("baton.bots.runtime.chat_json", side_effect=script), \
             patch("baton.bots.catalog._whatsapp_ready", return_value=(True, "OpenWA")), \
             patch("baton.channels.openwa.is_enabled", return_value=True):
            run = runtime.run_bot(self.bot.name, doc=self.lead)

        appr = frappe.get_doc("Baton Approval", frappe.get_all(
            "Baton Approval", filters={"reference_name": self.lead.name},
            order_by="creation desc", limit_page_length=1)[0].name)
        approval.resolve(appr, "Rejected", by="test")

        resume_script = _replies({"done": True, "summary": "gave up"})
        with patch("baton.bots.runtime.chat_json", side_effect=resume_script), \
             patch("baton.workflow.actions.whatsapp.send") as wa:
            runtime.run_bot(self.bot.name, resume_run=run, run_reason="approval")

        wa.assert_not_called()


class TestApprovalFallbackRecipient(FrappeTestCase):
    """A drafted send used to create a Baton Approval with nobody notified
    at all -- approval_channel/approval_recipient are bot-level settings a
    site using Draft mode for its send-mode, rather than gated_tools, has
    usually never touched. Whoever the record is assigned to is asked
    instead, the same person book_meeting's own rep notification already
    finds -- so a draft has somewhere to go by default."""

    def setUp(self):
        self.lead = _lead()
        self.bot = _bot("T Bot Fallback", connectors=("crm_leads",))
        self.run = frappe.get_doc({
            "doctype": "Baton Workflow Run", "bot": self.bot.name, "status": "Running",
        }).insert(ignore_permissions=True)
        self._original_mobile = frappe.db.get_value("User", "Administrator", "mobile_no")

    def tearDown(self):
        frappe.db.set_value("User", "Administrator", "mobile_no", self._original_mobile)
        _cleanup()

    def test_unconfigured_bot_falls_back_to_the_assignee_over_whatsapp(self):
        """approval_channel defaults to "Off" -- a real, valid value for the
        bot's own setting, but not one Baton Approval.channel accepts, so
        this doubles as a regression test for that crash too."""
        self.lead.db_set("_assign", json.dumps(["Administrator"]))
        frappe.db.set_value("User", "Administrator", "mobile_no", "+919000000001")

        with patch("baton.workflow.actions.whatsapp.send",
                   return_value={"sent": True}) as wa:
            name, hours = approval.request(self.bot, self.run, self.lead,
                                           "send_email", {"subject": "Hi", "body": "hi"})

        appr = frappe.get_doc("Baton Approval", name)
        self.assertEqual(appr.channel, "WhatsApp")
        self.assertEqual(appr.sent_to, "+919000000001")
        wa.assert_called_once()
        self.assertEqual(wa.call_args.kwargs["to"], "+919000000001")

    def test_an_assignee_with_no_number_falls_back_to_their_email(self):
        self.lead.db_set("_assign", json.dumps(["Administrator"]))
        frappe.db.set_value("User", "Administrator", "mobile_no", None)
        agent = frappe.db.get_value("CRM Telephony Agent", {"user": "Administrator"}, "name")
        if agent:
            frappe.db.set_value("CRM Telephony Agent", agent, "mobile_no", None)

        with patch("baton.bots.approval._send_email", return_value=True) as send_email:
            name, hours = approval.request(self.bot, self.run, self.lead,
                                           "send_email", {"subject": "Hi", "body": "hi"})

        appr = frappe.get_doc("Baton Approval", name)
        self.assertEqual(appr.channel, "Email")
        self.assertEqual(appr.sent_to, "Administrator")
        send_email.assert_called_once()

    def test_no_assignee_still_creates_a_valid_approval_record(self):
        """Nobody to ask is not a crash -- the approval still stands (an
        admin can find it in the CRM), it just goes undelivered."""
        self.lead.db_set("_assign", None)
        name, hours = approval.request(self.bot, self.run, self.lead,
                                       "send_email", {"subject": "Hi", "body": "hi"})
        appr = frappe.get_doc("Baton Approval", name)
        self.assertEqual(appr.status, "Pending")
        self.assertIn(appr.channel, ("Email", "WhatsApp"))
        self.assertFalse(appr.sent_to)

    def test_an_explicitly_configured_recipient_is_not_overridden(self):
        bot = _guarded(name="T Bot Explicit Approver", to="boss@example.com")
        self.lead.db_set("_assign", json.dumps(["Administrator"]))
        frappe.db.set_value("User", "Administrator", "mobile_no", "+919000000001")

        with patch("baton.bots.approval._send_email", return_value=True):
            name, hours = approval.request(bot, self.run, self.lead,
                                           "send_email", {"subject": "Hi", "body": "hi"})

        appr = frappe.get_doc("Baton Approval", name)
        self.assertEqual(appr.sent_to, "boss@example.com")
        self.assertEqual(appr.channel, "Email")
