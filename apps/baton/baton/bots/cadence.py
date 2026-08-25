"""Deterministic no-reply retry ladder for an initial-outreach bot.

wait_for_reply's timeout used to hand the model a bare "no_reply" and let it
freely decide what happens next -- "retry on WhatsApp" and "give up
entirely" looked identical to a model on a bad day. This computes the next
rung in code; the model only ever composes the wording for the rung it has
been placed on, never the schedule or the channel.

Reuses the exact Park("Timer", seconds) + quiet-hours-gated-send shape
already proven for quiet-hours retry (conversation/state.py:
quiet_hours_retry_seconds, bots/tools.py:_quiet_hours_retry) rather than
inventing a second kind of timed wait -- a cadence-driven send that lands
inside quiet hours reparks exactly the same way, for free, before
wait_for_reply is ever reached, so _cadence_pending below survives untouched.

Timings are a recommendation, confirmed with the user, not derived from
anything structural -- change FIRST_WAIT_HOURS/RUNGS if the schedule needs
to change; nothing else in this module encodes the numbers twice.
"""

import datetime

from frappe.utils import cint, now_datetime

DEFAULT_NEXT_MORNING_HOUR = 9

# How long to wait after the bot's own first, non-cadence message before the
# first scripted nudge -- not part of RUNGS, since RUNGS' own wait_hours/
# wait_until fields describe the wait that follows *sending that rung's
# message*, and there is no rung for the original message.
FIRST_WAIT_HOURS = 4

RUNGS = [
    {"channel": "WhatsApp", "wait_until_next_morning": True,
     "instruction": "Send a brief WhatsApp nudge referencing what you last "
                     "asked. Nothing else -- do not re-introduce yourself."},
    {"channel": "WhatsApp", "wait_hours": 4,
     "instruction": "Send one more brief WhatsApp nudge, referencing what "
                     "you last asked. If this goes unanswered too, you'll "
                     "move to email next -- make this one count."},
    {"channel": "Email", "wait_hours": 24,
     "instruction": "Switch to email. One message: summarise what you were "
                     "trying to learn, and invite them to reply whenever suits."},
]


def seconds_until_next_hour(hour=DEFAULT_NEXT_MORNING_HOUR, now=None):
    """Mirrors quiet_hours_retry_seconds()'s own date-rollover handling: if
    `hour` has already passed today, the target rolls to tomorrow."""
    now = now or now_datetime()
    candidate = datetime.datetime.combine(now.date(), datetime.time(hour, 0))
    if candidate <= now:
        candidate += datetime.timedelta(days=1)
    return max(int((candidate - now).total_seconds()), 60)


def _wait_seconds(rung, now=None):
    if rung.get("wait_until_next_morning"):
        return seconds_until_next_hour(DEFAULT_NEXT_MORNING_HOUR, now=now)
    return cint(rung.get("wait_hours")) * 3600


def first_wait_seconds():
    """How long to wait after the bot's own original message, before the
    first scripted nudge -- used by _wait_for_reply on a nurture-enabled
    bot's very first call, before any timeout (and so before advance()) has
    ever happened."""
    return FIRST_WAIT_HOURS * 3600


def advance(state):
    """Mutate state["vars"] to the next rung. Returns (rung, instruction);
    rung is None once the ladder is exhausted -- the caller escalates
    instead of looping back to the model."""
    attempt = cint((state.get("vars") or {}).get("followup_attempt")) + 1
    if attempt > len(RUNGS):
        return None, None
    rung = RUNGS[attempt - 1]
    v = state.setdefault("vars", {})
    v["followup_attempt"] = attempt
    v["_cadence_pending"] = {"channel": rung["channel"], "wait_seconds": _wait_seconds(rung)}
    return rung, f"Attempt {attempt} of {len(RUNGS)}: {rung['instruction']}"


def escalate(bot, run, doc, state):
    """No rungs left. Tell the assignee directly -- code-driven, no model
    turn -- and hand back a summary for the caller to finish the run with.

    A one-way heads-up, not a question -- goes through the same
    _assignee_number() + wa_action.send(doc=None, ...) pattern
    _notify_rep_of_booking already uses, not the new ask_assignee (which
    sends *and parks for a reply*, wrong shape for "please call them").
    """
    from baton.audit import log_action
    from baton.bots import tools as bot_tools
    from baton.workflow.actions import whatsapp as wa_action

    number = bot_tools._assignee_number(doc)
    attempts = cint((state.get("vars") or {}).get("followup_attempt"))
    last_q = (state.get("vars") or {}).get("last_question_asked")
    who = doc.get("lead_name") or doc.get("organization") or doc.name
    parts = [f"{who} hasn't answered after {attempts} follow-up(s) on WhatsApp and email."]
    if last_q:
        parts.append(f'Last asked: "{last_q}"')
    parts.append("Could you give them a call?")
    kind = "leads" if doc.doctype == "CRM Lead" else "deals"
    import frappe

    parts.append(f"{(frappe.utils.get_url() or '').rstrip('/')}/crm/{kind}/{doc.name}")
    message = " ".join(parts)[:1400]

    sent = False
    if number:
        outcome = wa_action.send(to=number, message=message, run=run,
                                 node=bot_tools._ShimNode("nurture_escalate"),
                                 doc=None, author="ai")
        sent = bool(isinstance(outcome, dict) and outcome.get("sent"))

    log_action("bot.nurture.escalated", actor_type="AI_AGENT",
               reference_doctype=doc.doctype, reference_name=doc.name,
               workflow_run=run.name, bot=bot.name,
               output={"assignee_notified": sent, "attempts": attempts})
    return (f"No reply after {attempts} attempt(s); "
            f"{'notified' if sent else 'tried to notify'} the assignee to call them.")
