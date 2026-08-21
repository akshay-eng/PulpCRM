"""Reads a conversation and scores the lead against a Qualification Profile.

Two deliberate constraints:

* **The model extracts; Python scores.** The LLM decides whether a criterion was
  answered and how well, on a 0-1 scale. The weighted arithmetic is done here,
  so the same conversation always yields the same score and a business can
  reason about its own thresholds. Asking the model for a final number invites
  it to drift.
* **It may not invent.** The profile's business context is injected, and the
  prompt forbids inferring an answer the customer never gave (spec §110).
"""

import json

import frappe
from frappe.utils import cint, flt

from baton.audit import log_action
from baton.conversation.thread import as_transcript
from baton.llm import chat_json, get_model_config

PROMPT = """You extract sales qualification facts from a conversation.

Business context (the only thing you may assume about the seller):
{context}

Criteria to assess:
{criteria}

Conversation so far:
{transcript}

Return ONLY this JSON:
{{
  "answers": {{
    "<criterion>": {{
      "answered": true|false,
      "value": "<what the customer actually said, verbatim or closely paraphrased>",
      "satisfaction": 0.0-1.0,
      "disqualifying": true|false
    }}
  }},
  "objections": "<concerns the customer raised, or empty>",
  "summary": "<2-3 sentences a salesperson could act on>",
  "next_question": "<the single most useful thing to ask next, or empty if nothing is missing>",
  "confidence": 0.0-1.0
}}

Rules:
- `answered` is false unless the customer actually addressed it. Never infer.
- `satisfaction` is how well their answer meets the stated acceptable range.
- `disqualifying` is true only if their answer matches the reject rule.
- Never invent pricing, capability, or delivery commitments.
- Quote the customer in `value`; do not editorialise."""


def _criteria_block(profile):
    lines = []
    for c in sorted(profile.criteria, key=lambda x: cint(x.priority)):
        bits = [f"- {c.criterion} (weight {c.weight}, {'required' if c.required else 'optional'})"]
        if c.acceptable:
            bits.append(f"  acceptable: {c.acceptable}")
        if c.reject_if:
            bits.append(f"  reject if: {c.reject_if}")
        lines.append("\n".join(bits))
    return "\n".join(lines)


def get_profile(name=None):
    if name:
        return frappe.get_cached_doc("Baton Qualification Profile", name)
    default = frappe.db.get_value(
        "Baton Qualification Profile", {"is_default": 1, "enabled": 1}, "name"
    )
    if not default:
        frappe.throw("No default Baton Qualification Profile is configured.")
    return frappe.get_cached_doc("Baton Qualification Profile", default)


def score_answers(profile, answers):
    """Weighted score in 0-100. Pure arithmetic -- no model involved."""
    total_weight = sum(cint(c.weight) for c in profile.criteria) or 1
    earned = 0.0
    disqualified = False
    missing = []

    for c in profile.criteria:
        got = answers.get(c.criterion) or {}
        if got.get("disqualifying"):
            disqualified = True
        if got.get("answered"):
            earned += cint(c.weight) * max(0.0, min(1.0, flt(got.get("satisfaction") or 0)))
        elif c.required:
            missing.append(c.criterion)

    score = 0 if disqualified else int(round(earned / total_weight * 100))
    return score, missing, disqualified


def band_for(profile, score):
    for b in profile.bands:
        if cint(b.min_score) <= score <= cint(b.max_score):
            return b.band, b.action
    return "Unbanded", "Nurture"


def qualify(reference_doctype, reference_name, profile_name=None, save=True):
    """Score a lead from its conversation. Returns the result document."""
    profile = get_profile(profile_name)
    transcript = as_transcript(reference_doctype, reference_name)
    model = get_model_config("Qualification")

    data = chat_json(
        [{"role": "user", "content": PROMPT.format(
            context=profile.business_context or "(none given)",
            criteria=_criteria_block(profile),
            transcript=transcript,
        )}],
        purpose="Qualification",
    )

    answers = data.get("answers") or {}
    score, missing, disqualified = score_answers(profile, answers)
    band, action = band_for(profile, score)
    complete = not missing

    result = frappe.get_doc({
        "doctype": "Baton Qualification Result",
        "reference_doctype": reference_doctype,
        "reference_name": reference_name,
        "profile": profile.name,
        "score": score,
        "band": band,
        "confidence": flt(data.get("confidence") or 0),
        "complete": 1 if complete else 0,
        "summary": (data.get("summary") or "")[:1000],
        "objections": (data.get("objections") or "")[:1000],
        "next_action": action,
        "missing": ", ".join(missing) or None,
        "next_question": (data.get("next_question") or "")[:500] or None,
        "answers": json.dumps(answers, indent=1)[:8000],
        "ai_model": model.name,
    })
    if save:
        result.insert(ignore_permissions=True)
        frappe.db.commit()

    log_action(
        "lead.qualified",
        actor_type="AI_AGENT",
        reference_doctype=reference_doctype,
        reference_name=reference_name,
        ai_model=model.name,
        provider=model.provider,
        decision=band,
        confidence=flt(data.get("confidence") or 0),
        reason=(
            f"score {score}/100, band {band}, action {action}. "
            + (f"Disqualified by rule. " if disqualified else "")
            + (f"Missing: {', '.join(missing)}." if missing else "All required answered.")
        ),
        output={"score": score, "band": band, "missing": missing},
    )
    return result


@frappe.whitelist()
def qualify_now(reference_doctype, reference_name, profile_name=None):
    frappe.has_permission(reference_doctype, "write", reference_name, throw=True)
    r = qualify(reference_doctype, reference_name, profile_name)
    return {
        "score": r.score, "band": r.band, "summary": r.summary,
        "missing": r.missing, "next_question": r.next_question,
        "next_action": r.next_action, "complete": bool(r.complete),
    }
