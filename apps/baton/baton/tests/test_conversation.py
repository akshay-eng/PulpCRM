"""The conversational agent's validation layer.

Everything here is about what happens when the model returns something wrong,
because that is the only interesting case: the happy path is one JSON object.
Prompt injection lives in this file too -- a customer typing Jinja must not have
it rendered, and one naming a service we do not sell must not get it.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from baton.agents import conversation as convo

from .test_engine import _lead

AGENT = "T Convo Agent"


def _agent():
    if frappe.db.exists("Baton Agent", AGENT):
        return frappe.get_doc("Baton Agent", AGENT)
    doc = frappe.get_doc({
        "doctype": "Baton Agent",
        "agent_name": AGENT,
        "enabled": 1,
        "goal": "Find out which service they want.",
        "business_context": "We build websites and apps.",
        "options": [
            {"key": "web", "label": "Website"},
            {"key": "app", "label": "Mobile app"},
        ],
        "outcomes": [
            {"key": "service", "label": "Service", "required": 1},
            {"key": "budget", "label": "Budget", "required": 0},
        ],
    }).insert(ignore_permissions=True)
    frappe.db.commit()
    return doc


class TestValidate(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = _agent()

    def test_a_clean_response_passes_through(self):
        out = convo.validate(
            {"action": "ask", "message": "Which service do you need?",
             "facts": {"budget": "about 40k"}, "choice": "web", "confidence": 0.8},
            self.agent, {})
        self.assertEqual(out["action"], "ask")
        self.assertEqual(out["facts"], {"budget": "about 40k"})
        self.assertEqual(out["choice"], "web")

    def test_an_unknown_action_is_not_trusted(self):
        out = convo.validate(
            {"action": "delete_everything", "message": "Hello?"}, self.agent, {})
        self.assertEqual(out["action"], "ask")
        self.assertIn("action", out["dropped"])

    def test_an_unknown_action_with_nothing_to_say_escalates(self):
        out = convo.validate({"action": "sudo", "message": ""}, self.agent, {})
        self.assertEqual(out["action"], "handoff")

    def test_undeclared_facts_are_dropped(self):
        """The model may not invent a field to fill in."""
        out = convo.validate(
            {"action": "ask", "message": "?",
             "facts": {"service": "web", "is_admin": "true"}}, self.agent, {})
        self.assertNotIn("is_admin", out["facts"])
        self.assertIn("fact:is_admin", out["dropped"])

    def test_an_undeclared_choice_is_dropped(self):
        """It cannot sell a service the business does not offer."""
        out = convo.validate(
            {"action": "ask", "message": "?", "choice": "blockchain"}, self.agent, {})
        self.assertIsNone(out["choice"])
        self.assertIn("choice:blockchain", out["dropped"])

    def test_finish_is_downgraded_when_a_required_fact_is_missing(self):
        """Python decides completeness, not the model."""
        out = convo.validate(
            {"action": "finish", "message": "Great, all set!"}, self.agent, {})
        self.assertEqual(out["action"], "ask")
        self.assertIn("finish:incomplete", out["dropped"])

    def test_finish_stands_once_the_required_fact_is_known(self):
        out = convo.validate(
            {"action": "finish", "message": ""}, self.agent, {"service": "web"})
        self.assertEqual(out["action"], "finish")

    def test_an_empty_ask_escalates_rather_than_sending_nothing(self):
        out = convo.validate({"action": "ask", "message": "   "}, self.agent, {})
        self.assertEqual(out["action"], "handoff")

    def test_a_long_message_is_cut(self):
        out = convo.validate(
            {"action": "ask", "message": "x" * 5000}, self.agent, {})
        self.assertLessEqual(len(out["message"]), convo.MAX_MESSAGE_CHARS)

    def test_urls_are_stripped(self):
        out = convo.validate(
            {"action": "ask", "message": "See http://evil.example/x now"},
            self.agent, {})
        self.assertNotIn("http", out["message"])

    def test_jinja_in_model_output_is_never_rendered(self):
        """engine._render is Jinja; model output must never reach it."""
        payload = "Hello {{ frappe.db.get_value('User','Administrator','api_key') }}"
        out = convo.validate({"action": "ask", "message": payload}, self.agent, {})
        # It survives verbatim -- as literal text, which is the point.
        self.assertIn("{{", out["message"])


class TestApplyFacts(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = _agent()

    def test_only_mapped_facts_are_written(self):
        """A fact with no admin-declared target must not touch the record."""
        lead = _lead()
        frappe.db.set_value("Baton Agent", AGENT, "modified", frappe.utils.now())
        frappe.clear_cache(doctype="Baton Agent")

        written = convo.apply_facts(AGENT, "CRM Lead", lead.name,
                                    {"service": "web", "budget": "40k"})
        self.assertEqual(written, {}, "wrote a field nobody mapped")


class TestDecideGuards(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = _agent()

    def test_a_disabled_agent_hands_off_without_calling_the_model(self):
        frappe.db.set_value("Baton Agent", AGENT, "enabled", 0)
        frappe.clear_cache(doctype="Baton Agent")
        lead = _lead()
        try:
            with patch.object(convo, "chat_json") as m:
                out = convo.decide(AGENT, "CRM Lead", lead.name)
            self.assertEqual(out["action"], "handoff")
            m.assert_not_called()
        finally:
            frappe.db.set_value("Baton Agent", AGENT, "enabled", 1)
            frappe.clear_cache(doctype="Baton Agent")

    def test_internal_vars_are_not_shown_to_the_model(self):
        """_turns is bookkeeping; leaking it invites the model to reason about it."""
        lead = _lead()
        with patch.object(convo, "chat_json", return_value={"action": "ask", "message": "hi"}) as m:
            convo.decide(AGENT, "CRM Lead", lead.name,
                         known={"service": "web", "_turns": {"n1": 3}})
        prompt = m.call_args.args[0][1]["content"]
        self.assertIn("service", prompt)
        self.assertNotIn("_turns", prompt)


class TestAIConversationNode(FrappeTestCase):
    """The node itself: it must speak through the gate and then wait."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = _agent()

    def setUp(self):
        from .test_handoff import _settings, _snapshot_settings

        self._saved = _snapshot_settings()
        _settings(ai_enabled=1, whatsapp_send_mode="Auto", quiet_hours_enabled=0,
                  ai_turn_cap=0, max_messages_per_lead_per_day=0)

    def tearDown(self):
        from .test_engine import _delete_test_workflows
        from .test_handoff import _settings

        _settings(**self._saved)
        _delete_test_workflows("T Convo")

    def _workflow(self):
        from .test_engine import _node, _workflow

        return _workflow("T Convo Flow", [
            _node("t", "Trigger", next_node="c"),
            _node("c", "AI Conversation", config={"agent": AGENT},
                  next_node="done", next_node_alt="human"),
            _node("done", "Update Field", config={"field": "status", "value": "Qualified"}),
            _node("human", "Update Field", config={"field": "status", "value": "Junk"}),
        ])

    def test_it_sends_the_question_and_parks(self):
        """Over OpenWA there is no service window, so a first greeting can go out."""
        from .test_parking import _account

        _account()
        # is_enabled() needs a session too -- a flag alone is not "OpenWA is on".
        frappe.db.set_single_value("Baton Settings", "openwa_enabled", 1)
        frappe.db.set_single_value("Baton Settings", "openwa_session_id", "test-session")
        frappe.db.commit()
        frappe.clear_cache(doctype="Baton Settings")
        self.addCleanup(self._disable_openwa)

        lead = _lead()
        wf = self._workflow()

        from baton.channels import openwa

        # Stub the bridge itself: this test is about the node, not about HTTP.
        with patch.object(convo, "chat_json",
                          return_value={"action": "ask", "message": "Website or app?"}), \
                patch.object(openwa, "send_text", return_value={"id": "wamid.test"}):
            from baton.workflow.engine import run_workflow
            run_name = run_workflow(wf.name, doc=lead)

        run = frappe.get_doc("Baton Workflow Run", run_name)
        self.assertEqual(run.status, "Waiting")
        self.assertEqual(run.waiting_for, "Reply")
        self.assertEqual(run.resume_node, "c", "it must re-enter itself to read the reply")

        sent = frappe.get_all("WhatsApp Message",
                              filters={"reference_name": lead.name, "baton_author": "ai"},
                              pluck="message")
        self.assertIn("Website or app?", sent)

    def _disable_openwa(self):
        frappe.db.set_single_value("Baton Settings", "openwa_enabled", 0)
        frappe.db.set_single_value("Baton Settings", "openwa_session_id", "")
        frappe.db.commit()
        frappe.clear_cache(doctype="Baton Settings")

    def test_meta_blocks_a_first_message_with_no_template(self):
        """Under Meta the 24-hour window has never opened, so free-form is refused.

        The run must still park rather than silently ending -- the lead is not
        lost, it is waiting for a human or for the deadline.
        """
        from .test_parking import _account

        _account()
        lead = _lead()
        wf = self._workflow()

        with patch.object(convo, "chat_json",
                          return_value={"action": "ask", "message": "Website or app?"}):
            from baton.workflow.engine import run_workflow
            run_name = run_workflow(wf.name, doc=lead)

        self.assertEqual(
            frappe.db.get_value("Baton Workflow Run", run_name, "status"), "Waiting")
        self.assertEqual(
            frappe.db.count("WhatsApp Message",
                            {"reference_name": lead.name, "baton_author": "ai"}), 0)
        skipped = frappe.get_all(
            "Baton Action Log",
            filters={"reference_name": lead.name, "action": "whatsapp.send",
                     "status": "Skipped"},
            fields=["reason"])
        self.assertTrue(skipped)
        self.assertIn("service window", skipped[0].reason.lower())

    def test_finish_continues_down_the_normal_branch(self):
        from .test_parking import _account

        _account()
        lead = _lead()
        wf = self._workflow()

        with patch.object(convo, "chat_json",
                          return_value={"action": "finish", "choice": "web",
                                        "facts": {"service": "web"}}):
            from baton.workflow.engine import run_workflow
            run_name = run_workflow(wf.name, doc=lead)

        lead.reload()
        self.assertEqual(lead.status, "Qualified")
        self.assertEqual(
            frappe.db.get_value("Baton Workflow Run", run_name, "status"), "Completed")

    def test_handoff_escalates_and_takes_the_alternate_branch(self):
        from baton.conversation.state import get_state
        from .test_parking import _account

        _account()
        lead = _lead()
        wf = self._workflow()

        with patch.object(convo, "chat_json",
                          return_value={"action": "handoff", "reason": "asked for a person"}):
            from baton.workflow.engine import run_workflow
            run_workflow(wf.name, doc=lead)

        lead.reload()
        self.assertEqual(lead.status, "Junk")
        self.assertEqual(get_state("CRM Lead", lead.name, create=False).state, "ESCALATED")

    def test_a_blocked_send_still_parks_rather_than_dropping_the_lead(self):
        """If the gate refuses, the run waits for the deadline -- it does not vanish."""
        from .test_handoff import _settings
        from .test_parking import _account

        _account()
        lead = _lead()
        wf = self._workflow()
        _settings(quiet_hours_enabled=1, quiet_start="00:00:00", quiet_end="23:59:59")

        with patch.object(convo, "chat_json",
                          return_value={"action": "ask", "message": "Website or app?"}):
            from baton.workflow.engine import run_workflow
            run_name = run_workflow(wf.name, doc=lead)

        run = frappe.get_doc("Baton Workflow Run", run_name)
        self.assertEqual(run.status, "Waiting")
        self.assertEqual(
            frappe.db.count("WhatsApp Message",
                            {"reference_name": lead.name, "baton_author": "ai"}), 0)


def tearDownModule():
    # The agent is inserted with a commit so the node can read it back, which
    # means it outlives the rollback and would sit in the site's agent list.
    from .test_engine import _delete_test_leads

    if frappe.db.exists("Baton Agent", AGENT):
        frappe.delete_doc("Baton Agent", AGENT, force=True, ignore_permissions=True)
    _delete_test_leads()
    frappe.db.commit()


class TestMessageStaysOnItsRecord(FrappeTestCase):
    """A message Baton addressed keeps the record it was addressed to.

    `crm.api.whatsapp.validate` re-resolves the reference from the phone number
    on every save and prefers a Deal. Left alone it moves a run's own message
    onto a different record, and then:

      * the reply never wakes the run, because resume_on_inbound looks for a
        Waiting run on the record the message is filed against
      * the send gate counts half the conversation against each record

    So the run parks on a lead and waits forever. This pins the fix.
    """

    def setUp(self):
        from .test_handoff import _settings, _snapshot_settings

        self._saved = _snapshot_settings()
        _settings(ai_enabled=1, whatsapp_send_mode="Auto", quiet_hours_enabled=0,
                  ai_turn_cap=0, max_messages_per_lead_per_day=0)

    def tearDown(self):
        from .test_engine import _delete_test_workflows
        from .test_handoff import _settings

        _settings(**self._saved)
        _delete_test_workflows("T Ref")
        for deal in frappe.get_all("CRM Deal",
                                   filters={"mobile_no": "+919999000042"}, pluck="name"):
            frappe.delete_doc("CRM Deal", deal, force=True, ignore_permissions=True)
        frappe.db.commit()

    def test_a_deal_sharing_the_number_does_not_steal_the_message(self):
        from unittest.mock import patch

        from baton.channels import openwa

        from .test_engine import _lead, _node, _workflow
        from .test_parking import _account

        _account()
        frappe.db.set_single_value("Baton Settings", "openwa_enabled", 1)
        frappe.db.set_single_value("Baton Settings", "openwa_session_id", "test-session")
        frappe.db.commit()
        frappe.clear_document_cache("Baton Settings", "Baton Settings")
        self.addCleanup(self._disable_openwa)

        lead = _lead(mobile_no="+919999000042")
        # The same number on a Deal is what CRM's hook prefers.
        frappe.get_doc({"doctype": "CRM Deal",
                        "mobile_no": "+919999000042"}).insert(ignore_permissions=True)
        frappe.db.commit()

        wf = _workflow("T Ref Flow", [
            _node("t", "Trigger", next_node="s"),
            _node("s", "Send WhatsApp", config={"message": "Hello there"}),
        ])
        with patch.object(openwa, "send_text", return_value={"id": "wamid.ref"}):
            from baton.workflow.engine import run_workflow
            run_workflow(wf.name, doc=lead)

        rows = frappe.get_all("WhatsApp Message",
                              filters={"message": "Hello there"},
                              fields=["reference_doctype", "reference_name"])
        self.assertTrue(rows, "the message must exist")
        self.assertEqual(rows[0]["reference_doctype"], "CRM Lead")
        self.assertEqual(rows[0]["reference_name"], lead.name)

    def _disable_openwa(self):
        frappe.db.set_single_value("Baton Settings", "openwa_enabled", 0)
        frappe.db.set_single_value("Baton Settings", "openwa_session_id", "")
        frappe.db.commit()
        frappe.clear_document_cache("Baton Settings", "Baton Settings")
