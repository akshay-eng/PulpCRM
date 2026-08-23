"""Human handoff and send-gate tests.

Spec §80-§81. These are the tests that matter most: if they pass, the AI cannot
talk over a human. If they fail, the product embarrasses its customer.
"""

import json

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from baton.conversation.state import (
    can_ai_send,
    cancel_pending_ai_actions,
    get_state,
    mark_human_intervention,
    review_expired_cooldowns,
    set_state,
)
from baton.workflow.engine import run_workflow


def _lead(**kw):
    values = {
        "doctype": "CRM Lead", "first_name": "Handoff", "last_name": "Test",
        "lead_name": "Handoff Test", "mobile_no": "+919999000123",
    }
    values.update(kw)
    return frappe.get_doc(values).insert(ignore_permissions=True)


# Baton Settings is a singleton, so tests that change it must put it back --
# otherwise the suite silently reconfigures the running site.
POLICY_FIELDS = (
    "ai_enabled", "whatsapp_send_mode", "email_send_mode", "quiet_hours_enabled",
    "quiet_start", "quiet_end", "max_messages_per_lead_per_day",
    "human_cooldown_minutes", "default_resume_policy", "ai_turn_cap",
)


def _snapshot_settings():
    s = frappe.get_single("Baton Settings")
    return {f: s.get(f) for f in POLICY_FIELDS}


def _settings(**kw):
    s = frappe.get_single("Baton Settings")
    for k, v in kw.items():
        setattr(s, k, v)
    s.save(ignore_permissions=True)
    # Must commit. The workflow engine commits mid-test, which promotes whatever
    # this test set into the durable transaction; FrappeTestCase then rolls back
    # the restore, leaving the site permanently reconfigured by the test run.
    frappe.db.commit()
    # clear_cache(doctype=...) drops the *meta* cache, not the cached document.
    # The send gate reads through get_cached_doc, so without this line a test
    # sets ai_enabled=1, the gate keeps reading the site's stored 0, and the
    # test passes or fails depending on how the site happens to be configured
    # -- which is how it passed for weeks and then started failing when the
    # site was switched off.
    frappe.clear_document_cache("Baton Settings", "Baton Settings")
    frappe.clear_cache(doctype="Baton Settings")
    return s



def _delete_test_workflows(*prefixes):
    """The engine commits, so rollback cannot remove what tests created."""
    for prefix in prefixes:
        for name in frappe.get_all("Baton Workflow",
                                   filters={"workflow_name": ["like", f"{prefix}%"]},
                                   pluck="name"):
            for run in frappe.get_all("Baton Workflow Run",
                                      filters={"workflow": name}, pluck="name"):
                frappe.delete_doc("Baton Workflow Run", run, force=True,
                                  ignore_permissions=True)
            frappe.delete_doc("Baton Workflow", name, force=True, ignore_permissions=True)
    frappe.db.commit()


class PolicyTestCase(FrappeTestCase):
    """Restores Baton Settings after every test."""

    def setUp(self):
        self._saved = _snapshot_settings()
        super().setUp()

    def tearDown(self):
        _settings(**self._saved)
        super().tearDown()


def _node(node_id, node_type, **kw):
    base = {"node_id": node_id, "node_type": node_type, "label": node_id}
    if "config" in kw:
        kw["config"] = json.dumps(kw["config"])
    base.update(kw)
    return base


def _workflow(name, nodes):
    if frappe.db.exists("Baton Workflow", name):
        frappe.delete_doc("Baton Workflow", name, force=True, ignore_permissions=True)
    return frappe.get_doc({
        "doctype": "Baton Workflow", "workflow_name": name, "enabled": 1,
        "trigger_type": "Manual", "nodes": nodes,
    }).insert(ignore_permissions=True)


class TestSendGate(PolicyTestCase):
    def setUp(self):
        super().setUp()
        _settings(ai_enabled=1, whatsapp_send_mode="Auto", email_send_mode="Draft",
                  quiet_hours_enabled=0, max_messages_per_lead_per_day=0,
                  human_cooldown_minutes=360, ai_turn_cap=0)

    def test_allowed_by_default(self):
        lead = _lead()
        allowed, mode, why = can_ai_send("CRM Lead", lead.name)
        self.assertTrue(allowed, why)
        self.assertEqual(mode, "Auto")

    def test_global_switch_refuses(self):
        _settings(ai_enabled=0)
        lead = _lead()
        allowed, _, why = can_ai_send("CRM Lead", lead.name)
        self.assertFalse(allowed)
        self.assertIn("switched off globally", why)

    def test_channel_off_refuses(self):
        _settings(whatsapp_send_mode="Off")
        lead = _lead()
        allowed, _, why = can_ai_send("CRM Lead", lead.name, channel="WhatsApp")
        self.assertFalse(allowed)

    def test_email_defaults_to_draft_mode(self):
        """The owner chose auto WhatsApp, drafted email."""
        lead = _lead()
        allowed, mode, _ = can_ai_send("CRM Lead", lead.name, channel="Email")
        self.assertTrue(allowed)
        self.assertEqual(mode, "Draft")

    def test_do_not_contact_refuses(self):
        lead = _lead()
        set_state("CRM Lead", lead.name, "DO_NOT_CONTACT")
        allowed, _, why = can_ai_send("CRM Lead", lead.name)
        self.assertFalse(allowed)
        self.assertIn("do-not-contact", why)

    def test_turn_cap_refuses(self):
        _settings(ai_turn_cap=2)
        lead = _lead()
        st = get_state("CRM Lead", lead.name)
        st.ai_turn_count = 2
        st.save(ignore_permissions=True)
        allowed, _, why = can_ai_send("CRM Lead", lead.name)
        self.assertFalse(allowed)
        self.assertIn("without a reply", why)

    def test_quiet_hours_refuse(self):
        """A window covering the whole day must always be inside."""
        _settings(quiet_hours_enabled=1, quiet_start="00:00:00", quiet_end="23:59:59")
        lead = _lead()
        allowed, _, why = can_ai_send("CRM Lead", lead.name)
        self.assertFalse(allowed)
        self.assertIn("Quiet hours", why)


class TestHumanIntervention(PolicyTestCase):
    def setUp(self):
        super().setUp()
        _settings(ai_enabled=1, whatsapp_send_mode="Auto", quiet_hours_enabled=0,
                  max_messages_per_lead_per_day=0, human_cooldown_minutes=360,
                  ai_turn_cap=0)

    def test_human_message_pauses_ai(self):
        lead = _lead()
        mark_human_intervention("CRM Lead", lead.name, user="Administrator")

        st = get_state("CRM Lead", lead.name)
        self.assertEqual(st.state, "HUMAN_ACTIVE")
        self.assertIsNotNone(st.paused_until)

        allowed, _, why = can_ai_send("CRM Lead", lead.name)
        self.assertFalse(allowed, "AI must be silent after a human replies")
        self.assertIn("HUMAN_ACTIVE", why)

    def test_the_pause_is_visible_as_a_comment_not_only_the_audit_log(self):
        """A pause nobody can see without knowing to check Baton Action Log
        is a pause a salesperson will not notice."""
        lead = _lead()
        mark_human_intervention("CRM Lead", lead.name, user="Administrator")

        comments = frappe.get_all(
            "Comment", filters={"reference_doctype": "CRM Lead", "reference_name": lead.name,
                                "comment_type": "Comment"},
            fields=["content"])
        self.assertTrue(comments, "no Comment was left on the Lead's timeline")
        self.assertIn("paused", comments[0].content.lower())

    def test_cooldown_is_configurable(self):
        _settings(human_cooldown_minutes=15)
        lead = _lead()
        st = mark_human_intervention("CRM Lead", lead.name)
        delta = (st.paused_until - now_datetime()).total_seconds()
        self.assertGreater(delta, 13 * 60)
        self.assertLess(delta, 17 * 60)

    def test_pending_waiting_run_is_cancelled(self):
        """Spec §81 -- the edge case that breaks products.

        AI sends at 10:00, a follow-up is scheduled for 14:00, the human replies
        at 12:00. At 14:00 nothing must go out.
        """
        lead = _lead()
        _workflow("H Wait", [
            _node("t", "Trigger", next_node="w"),
            _node("w", "Wait", config={"amount": 4, "unit": "hours"}, next_node="send"),
            _node("send", "Send WhatsApp",
                  config={"to": "{{ doc.mobile_no }}", "message": "Just following up", "author": "ai"}),
        ])
        run_name = run_workflow("H Wait", doc=lead)
        self.assertEqual(frappe.db.get_value("Baton Workflow Run", run_name, "status"), "Waiting")

        # The human replies before the follow-up is due.
        mark_human_intervention("CRM Lead", lead.name)

        run = frappe.get_doc("Baton Workflow Run", run_name)
        self.assertEqual(run.status, "Cancelled")
        self.assertIsNone(run.resume_at)
        self.assertIn("Human intervention", run.cancelled_reason)

        # And even if something tried to resume it, the gate refuses.
        allowed, _, _ = can_ai_send("CRM Lead", lead.name)
        self.assertFalse(allowed)

    def test_pending_approvals_are_withdrawn(self):
        lead = _lead()
        frappe.get_doc({
            "doctype": "Baton Approval", "kind": "Send Message", "status": "Pending",
            "draft_text": "queued", "reference_doctype": "CRM Lead",
            "reference_name": lead.name,
        }).insert(ignore_permissions=True)

        result = cancel_pending_ai_actions("CRM Lead", lead.name)
        self.assertEqual(result["approvals"], 1)

    def test_engine_suppresses_send_during_cooldown(self):
        """End to end: the node runs, but the gate stops the message."""
        lead = _lead()
        mark_human_intervention("CRM Lead", lead.name)

        _workflow("H Suppress", [
            _node("t", "Trigger", next_node="send"),
            _node("send", "Send WhatsApp",
                  config={"to": "{{ doc.mobile_no }}", "message": "hello", "author": "ai"}),
        ])
        run_name = run_workflow("H Suppress", doc=lead)

        step = frappe.get_doc("Baton Workflow Run", run_name).steps[-1]
        self.assertIn("skipped", (step.output or ""))

        # No WhatsApp Message may exist for this lead.
        sent = frappe.db.count("WhatsApp Message", {"reference_name": lead.name})
        self.assertEqual(sent, 0, "AI sent during the human cooldown")

        # And the refusal is explained in the audit log (spec §74).
        log = frappe.get_all("Baton Action Log",
                             filters={"reference_name": lead.name, "action": "whatsapp.send",
                                      "status": "Skipped"},
                             fields=["reason", "decision"])
        self.assertTrue(log)
        self.assertEqual(log[0].decision, "SUPPRESSED")
        self.assertIn("HUMAN_ACTIVE", log[0].reason)


class TestCooldownExpiry(PolicyTestCase):
    def setUp(self):
        super().setUp()
        # Quiet hours must be off, or these assertions depend on the wall clock:
        # the default 22:00-08:00 window makes can_ai_send() refuse at night.
        _settings(ai_enabled=1, human_cooldown_minutes=360, quiet_hours_enabled=0,
                  whatsapp_send_mode="Auto", max_messages_per_lead_per_day=0,
                  ai_turn_cap=0)

    def _expire(self, lead):
        st = get_state("CRM Lead", lead.name)
        st.paused_until = add_to_date(now_datetime(), minutes=-1)
        st.save(ignore_permissions=True)
        return st

    def test_auto_resume(self):
        lead = _lead()
        mark_human_intervention("CRM Lead", lead.name)
        st = self._expire(lead)
        st.db_set("resume_policy", "AUTO_RESUME")

        review_expired_cooldowns()
        self.assertEqual(get_state("CRM Lead", lead.name).state, "AI_ACTIVE")

    def test_require_approval_waits(self):
        lead = _lead()
        mark_human_intervention("CRM Lead", lead.name)
        st = self._expire(lead)
        st.db_set("resume_policy", "REQUIRE_APPROVAL")

        review_expired_cooldowns()
        self.assertEqual(get_state("CRM Lead", lead.name).state, "AI_REVIEW_PENDING")
        # Still not allowed to speak.
        allowed, _, _ = can_ai_send("CRM Lead", lead.name)
        self.assertFalse(allowed)

    def test_remain_paused(self):
        lead = _lead()
        mark_human_intervention("CRM Lead", lead.name)
        st = self._expire(lead)
        st.db_set("resume_policy", "REMAIN_PAUSED")

        review_expired_cooldowns()
        self.assertEqual(get_state("CRM Lead", lead.name).state, "PAUSED")

    def test_the_transition_is_visible_as_a_comment(self):
        lead = _lead()
        mark_human_intervention("CRM Lead", lead.name)
        before = frappe.db.count("Comment", {"reference_doctype": "CRM Lead",
                                             "reference_name": lead.name})
        st = self._expire(lead)
        st.db_set("resume_policy", "AUTO_RESUME")

        review_expired_cooldowns()

        after = frappe.db.count("Comment", {"reference_doctype": "CRM Lead",
                                            "reference_name": lead.name})
        self.assertGreater(after, before)


class TestHumanOverrideWins(PolicyTestCase):
    def test_human_can_force_resume(self):
        """Spec §29 -- the human always wins."""
        _settings(ai_enabled=1, whatsapp_send_mode="Auto", quiet_hours_enabled=0,
                  max_messages_per_lead_per_day=0, ai_turn_cap=0)
        lead = _lead()
        mark_human_intervention("CRM Lead", lead.name)
        self.assertFalse(can_ai_send("CRM Lead", lead.name)[0])

        set_state("CRM Lead", lead.name, "AI_ACTIVE", reason="owner handed back")
        self.assertTrue(can_ai_send("CRM Lead", lead.name)[0])


def tearDownModule():
    # One shared sweep rather than a copy per module: it also clears orphaned
    # approvals, which is what made an order-dependent failure reproducible.
    from .test_engine import _delete_test_leads

    _delete_test_leads('Handoff Test')
    _delete_test_workflows('H ')
