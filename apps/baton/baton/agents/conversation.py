"""A conversational agent that may choose between three actions and nothing else.

The model never sends, never names a CRM field, and never decides it is
finished. It returns a small JSON object; Python validates it against what an
admin declared on the `Baton Agent`, and the node acts on the result.

This is the same medicine qualification.py uses -- *"the model extracts, Python
decides"* -- applied to a conversation instead of a score. The failure it
prevents is the one that matters commercially: an agent that improvises a
service you do not sell, or decides a lead is qualified because it sounded
enthusiastic.
"""

import json
import re

import frappe

from baton.audit import log_action
from baton.conversation.thread import as_transcript
from baton.llm import chat_json

ACTIONS = ("ask", "finish", "handoff")

# WhatsApp will take more, but a bot writing paragraphs at a customer reads as a
# bot. Cutting here is cheaper than asking the model nicely.
MAX_MESSAGE_CHARS = 900

CONTRACT = """Return ONLY this JSON object and nothing else:
{
  "action": "ask" | "finish" | "handoff",
  "message": "<what to say to the customer; empty unless action is ask>",
  "facts": { "<fact key>": "<the customer's own words>" },
  "choice": "<one option key, or null>",
  "confidence": 0.0,
  "reason": "<one sentence for our records; never shown to the customer>"
}

Rules:
- "ask" is the only action that speaks. Ask ONE question.
- Only report a fact the customer actually gave. Never infer one.
- "choice" must be one of the option keys, or null if they have not said.
- Use "handoff" if they ask for a person, complain, or you cannot help.
- Quote the customer in "facts". Do not editorialise."""


def _options_block(agent):
    if not agent.options:
        return "(no options declared)"
    lines = []
    for o in agent.options:
        line = f"- {o.key} — {o.label}"
        if o.description:
            line += f": {o.description}"
        if o.synonyms:
            line += f" (also called: {o.synonyms})"
        lines.append(line)
    return "\n".join(lines)


def _missing(agent, known):
    return [o.key for o in agent.outcomes if o.required and not known.get(o.key)]


def _system_prompt(agent, known):
    missing = _missing(agent, known)
    signature = frappe.db.get_single_value("Baton Settings", "agent_signature") or ""
    return "\n\n".join(filter(None, [
        f"You are having a short {agent.channel} conversation on behalf of a sales team.",
        f"Goal: {agent.goal}",
        f"Tone: {agent.persona}" if agent.persona else "",
        f"About the business (the only thing you may assume):\n{agent.business_context}"
        if agent.business_context else "",
        f"Rules you must not break:\n{agent.guardrails}" if agent.guardrails else "",
        f"You are choosing between these options:\n{_options_block(agent)}",
        f"Still to find out: {', '.join(missing)}" if missing else
        "You have everything you need.",
        f"Sign off as: {signature}" if signature else "",
        CONTRACT,
    ]))


def _user_prompt(agent, reference_doctype, reference_name, known):
    known_block = "\n".join(f"- {k}: {v}" for k, v in known.items() if not k.startswith("_"))
    transcript = as_transcript(reference_doctype, reference_name,
                               limit=agent.transcript_limit or 30)
    # The customer's words live inside this delimited block and never in the
    # system prompt. That is the cheap, effective prompt-injection mitigation:
    # instructions they type are data here, not instructions.
    return (
        f"Known so far:\n{known_block or '(nothing yet)'}\n\n"
        f"--- CONVERSATION ---\n{transcript}\n--- END CONVERSATION ---"
    )


def _strip_urls(text):
    return re.sub(r"https?://\S+", "", text or "").strip()


def validate(raw, agent, known):
    """Coerce whatever the model returned into something safe to act on.

    Nothing here trusts the model. An unknown action becomes a sensible one, an
    undeclared fact is dropped, and completeness is decided by Python.
    """
    dropped = []

    action = (raw.get("action") or "").strip().lower()
    if action not in ACTIONS:
        # A model that produced prose instead of an action was probably trying
        # to say something; if it was not, escalate rather than guess again.
        action = "ask" if (raw.get("message") or "").strip() else "handoff"
        dropped.append("action")

    declared_facts = {o.key for o in agent.outcomes}
    facts = {}
    for k, v in (raw.get("facts") or {}).items():
        if k in declared_facts and v not in (None, ""):
            facts[k] = str(v)[:500]
        else:
            dropped.append(f"fact:{k}")

    declared_options = {o.key for o in agent.options}
    choice = raw.get("choice")
    if choice not in declared_options:
        if choice not in (None, ""):
            dropped.append(f"choice:{choice}")
        choice = None

    message = str(raw.get("message") or "")[:MAX_MESSAGE_CHARS]
    if message:
        message = _strip_urls(message)

    merged = dict(known)
    merged.update(facts)
    if choice:
        merged.setdefault("service", choice)

    # Python owns "are we done", not the model. A model that says finish while a
    # required fact is missing is asking a question it has not asked yet.
    if action == "finish" and _missing(agent, merged):
        action = "ask"
        dropped.append("finish:incomplete")

    if action == "ask" and not message:
        action = "handoff"
        dropped.append("ask:empty")

    return {
        "action": action,
        "message": message,
        "facts": facts,
        "choice": choice,
        "confidence": float(raw.get("confidence") or 0),
        "reason": str(raw.get("reason") or "")[:500],
        "dropped": dropped,
    }


def decide(agent_name, reference_doctype, reference_name, known=None, run=None, node_id=None):
    """Ask the model what to do next. Returns a validated decision dict."""
    agent = frappe.get_cached_doc("Baton Agent", agent_name)
    if not agent.enabled:
        return {"action": "handoff", "message": "", "facts": {}, "choice": None,
                "confidence": 0.0, "reason": "Agent is switched off", "dropped": []}

    known = {k: v for k, v in (known or {}).items() if not str(k).startswith("_")}

    raw = chat_json(
        [
            {"role": "system", "content": _system_prompt(agent, known)},
            {"role": "user",
             "content": _user_prompt(agent, reference_doctype, reference_name, known)},
        ],
        purpose=agent.purpose or "Conversation",
    )
    decision = validate(raw, agent, known)

    log_action(
        "agent.decide",
        actor_type="AI_AGENT",
        reference_doctype=reference_doctype,
        reference_name=reference_name,
        workflow_run=run.name if run else None,
        node_id=node_id,
        decision=decision["action"],
        confidence=decision["confidence"],
        reason=decision["reason"],
        input={"agent": agent_name, "known": list(known),
               "dropped": decision["dropped"]},
        output={k: v for k, v in decision.items() if k != "dropped"},
    )
    return decision


def apply_facts(agent_name, reference_doctype, reference_name, facts):
    """Write facts onto the CRM record, but only where an admin mapped them.

    The model supplies values; a human decided, once, which field each value is
    allowed to touch. That is why prompt injection cannot make it write to
    somewhere it should not.
    """
    agent = frappe.get_cached_doc("Baton Agent", agent_name)
    written = {}
    for outcome in agent.outcomes:
        if not outcome.target_field or outcome.key not in facts:
            continue
        target_dt = outcome.target_doctype or reference_doctype
        target_dn = reference_name if target_dt == reference_doctype else None
        if not target_dn or not frappe.db.has_column(target_dt, outcome.target_field):
            continue
        frappe.db.set_value(target_dt, target_dn, outcome.target_field,
                            facts[outcome.key])
        written[outcome.target_field] = facts[outcome.key]

    if written:
        frappe.db.commit()
    return written


@frappe.whitelist()
def dry_run(agent_name, reference_doctype, reference_name):
    """What would the agent say right now? Sends nothing."""
    frappe.only_for(["System Manager", "Sales Manager"])
    return decide(agent_name, reference_doctype, reference_name)
