"""Qualification scoring and conversion tests.

Scoring is pure arithmetic on purpose -- the model decides whether a criterion
was answered, Python decides what that is worth. That split is what makes these
tests possible without a network call.
"""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from baton.agents import qualification as q
from baton.agents.conversion import should_convert


def _profile():
    return q.get_profile()


def _answers(**kw):
    """Build an answers dict; each value is (answered, satisfaction, disqualifying)."""
    out = {}
    for k, v in kw.items():
        name = k.replace("_", " ").title()
        answered, sat, dq = v
        out[name] = {"answered": answered, "value": "x", "satisfaction": sat,
                     "disqualifying": dq}
    return out



def _delete_test_leads(*lead_names):
    """The engine commits mid-test, so FrappeTestCase's rollback cannot remove
    leads these tests create. Left alone they accumulate in the real CRM."""
    for nm in lead_names:
        for lead in frappe.get_all("CRM Lead", filters={"lead_name": nm}, pluck="name"):
            for dt in ("WhatsApp Message", "Baton Conversation State",
                       "Baton Qualification Result"):
                if not frappe.db.exists("DocType", dt):
                    continue
                for row in frappe.get_all(dt, filters={"reference_name": lead}, pluck="name"):
                    frappe.delete_doc(dt, row, force=True, ignore_permissions=True)
            frappe.delete_doc("CRM Lead", lead, force=True, ignore_permissions=True)
    frappe.db.commit()

class TestScoring(FrappeTestCase):
    def test_all_perfect_is_100(self):
        p = _profile()
        answers = {c.criterion: {"answered": True, "satisfaction": 1.0,
                                 "disqualifying": False} for c in p.criteria}
        score, missing, dq = q.score_answers(p, answers)
        self.assertEqual(score, 100)
        self.assertEqual(missing, [])
        self.assertFalse(dq)

    def test_nothing_answered_is_zero_and_lists_required(self):
        p = _profile()
        score, missing, dq = q.score_answers(p, {})
        self.assertEqual(score, 0)
        # Requirement, Budget and Timeline are required in the default profile.
        self.assertIn("Requirement", missing)
        self.assertIn("Budget", missing)
        self.assertNotIn("Urgency", missing)  # optional

    def test_partial_satisfaction_is_proportional(self):
        p = _profile()
        answers = {c.criterion: {"answered": True, "satisfaction": 0.5,
                                 "disqualifying": False} for c in p.criteria}
        score, _, _ = q.score_answers(p, answers)
        self.assertEqual(score, 50)

    def test_weights_are_respected(self):
        """Requirement is 25 of 100; answering only it should score 25."""
        p = _profile()
        answers = {"Requirement": {"answered": True, "satisfaction": 1.0,
                                   "disqualifying": False}}
        score, _, _ = q.score_answers(p, answers)
        self.assertEqual(score, 25)

    def test_disqualifying_answer_zeroes_the_score(self):
        p = _profile()
        answers = {c.criterion: {"answered": True, "satisfaction": 1.0,
                                 "disqualifying": False} for c in p.criteria}
        answers["Budget"]["disqualifying"] = True
        score, _, dq = q.score_answers(p, answers)
        self.assertEqual(score, 0, "a disqualifying answer must override a high score")
        self.assertTrue(dq)

    def test_satisfaction_is_clamped(self):
        """A model returning 5.0 must not inflate the score past 100."""
        p = _profile()
        answers = {c.criterion: {"answered": True, "satisfaction": 5.0,
                                 "disqualifying": False} for c in p.criteria}
        score, _, _ = q.score_answers(p, answers)
        self.assertEqual(score, 100)


class TestBands(FrappeTestCase):
    def test_band_boundaries(self):
        p = _profile()
        for score, expected in ((0, "Cold"), (39, "Cold"), (40, "Warm"), (69, "Warm"),
                                (70, "Qualified"), (84, "Qualified"),
                                (85, "Hot"), (100, "Hot")):
            band, _ = q.band_for(p, score)
            self.assertEqual(band, expected, f"score {score}")

    def test_only_hot_band_converts(self):
        p = _profile()
        self.assertEqual(q.band_for(p, 90)[1], "Create deal")
        self.assertEqual(q.band_for(p, 75)[1], "Human review")
        self.assertEqual(q.band_for(p, 20)[1], "Nurture")


class TestQualifyWithStubbedModel(FrappeTestCase):
    def _lead(self):
        return frappe.get_doc({
            "doctype": "CRM Lead", "first_name": "Qual", "last_name": "Test",
            "lead_name": "Qual Test", "mobile_no": "+919000000001",
        }).insert(ignore_permissions=True)

    def test_result_is_persisted_with_traceable_fields(self):
        lead = self._lead()
        p = _profile()
        payload = {
            "answers": {c.criterion: {"answered": True, "value": "said so",
                                      "satisfaction": 1.0, "disqualifying": False}
                        for c in p.criteria},
            "objections": "",
            "summary": "Ready to buy.",
            "next_question": "",
            "confidence": 0.9,
        }
        with patch.object(q, "chat_json", return_value=payload):
            r = q.qualify("CRM Lead", lead.name)

        self.assertEqual(r.score, 100)
        self.assertEqual(r.band, "Hot")
        self.assertTrue(r.complete)
        self.assertEqual(r.next_action, "Create deal")
        self.assertTrue(r.ai_model, "the model used must be recorded")
        self.assertTrue(json.loads(r.answers))

    def test_incomplete_blocks_conversion(self):
        lead = self._lead()
        payload = {
            "answers": {"Requirement": {"answered": True, "value": "site",
                                        "satisfaction": 1.0, "disqualifying": False}},
            "summary": "Only the requirement is known.",
            "next_question": "What is your budget?",
            "confidence": 0.5,
        }
        with patch.object(q, "chat_json", return_value=payload):
            r = q.qualify("CRM Lead", lead.name)

        self.assertFalse(r.complete)
        self.assertIn("Budget", r.missing)
        self.assertEqual(r.next_question, "What is your budget?")

        ok, reason = should_convert(lead.name)
        self.assertFalse(ok)
        self.assertIn("incomplete", reason.lower())

    def test_warm_lead_does_not_convert(self):
        lead = self._lead()
        p = _profile()
        payload = {
            "answers": {c.criterion: {"answered": True, "value": "meh",
                                      "satisfaction": 0.5, "disqualifying": False}
                        for c in p.criteria},
            "summary": "Lukewarm.", "confidence": 0.6,
        }
        with patch.object(q, "chat_json", return_value=payload):
            r = q.qualify("CRM Lead", lead.name)

        self.assertEqual(r.band, "Warm")
        ok, reason = should_convert(lead.name)
        self.assertFalse(ok)
        self.assertIn("Nurture", reason)


def tearDownModule():
    _delete_test_leads('Qual Test')
