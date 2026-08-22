r"""Human handoff state machine and the outbound send gate.

This is the feature the product lives or dies on. If a human replies to a
customer and the AI then sends its queued follow-up anyway, the customer sees
two voices contradicting each other and the business looks broken.

    AI_ACTIVE --human sends--> HUMAN_ACTIVE --cooldown--> AI_REVIEW_PENDING --> AI_ACTIVE
                                                                            \-> PAUSED

Every outbound AI message must pass `can_ai_send()`. There is deliberately no
second path to sending.
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

# States in which the AI may not speak at all.
#
# AI_REVIEW_PENDING belongs here: under REQUIRE_APPROVAL the cooldown expiring
# means "a human may now decide", NOT "the AI may resume". Leaving it out let the
# AI speak the moment the timer lapsed, which is the opposite of the policy.
SILENT_STATES = {
    "HUMAN_ACTIVE", "AI_REVIEW_PENDING", "PAUSED",
    "ESCALATED", "CLOSED", "DO_NOT_CONTACT",
}


def get_state(reference_doctype, reference_name, create=True):
    """Fetch the conversation state row, creating it on first use."""
    name = frappe.db.get_value(
        "Baton Conversation State",
        {"reference_doctype": reference_doctype, "reference_name": reference_name},
        "name",
    )
    if name:
        return frappe.get_doc("Baton Conversation State", name)
    if not create:
        return None

    settings = frappe.get_cached_doc("Baton Settings")
    return frappe.get_doc({
        "doctype": "Baton Conversation State",
        "reference_doctype": reference_doctype,
        "reference_name": reference_name,
        "state": "AI_ACTIVE",
        "channel": "Any",
        "resume_policy": settings.get("default_resume_policy") or "REQUIRE_APPROVAL",
    }).insert(ignore_permissions=True)


# --------------------------------------------------------------- transitions

def mark_human_intervention(reference_doctype, reference_name, user=None, reason=None):
    """A human sent manually. Silence the AI for the configured cooldown."""
    from baton.audit import log_action

    settings = frappe.get_cached_doc("Baton Settings")
    cooldown = cint(settings.get("human_cooldown_minutes") or 360)

    st = get_state(reference_doctype, reference_name)
    st.state = "HUMAN_ACTIVE"
    st.paused_until = add_to_date(now_datetime(), minutes=cooldown)
    st.paused_by = user or frappe.session.user
    st.pause_reason = reason or "Human sent a message manually"
    st.last_human_message_at = now_datetime()
    st.save(ignore_permissions=True)

    cancelled = cancel_pending_ai_actions(reference_doctype, reference_name)

    log_action(
        "human.intervention.detected",
        actor_type="HUMAN",
        actor_id=st.paused_by,
        reference_doctype=reference_doctype,
        reference_name=reference_name,
        decision="PAUSE_AI",
        reason=f"AI paused until {st.paused_until} ({cooldown} min); "
               f"cancelled {cancelled['runs']} run(s), {cancelled['approvals']} approval(s)",
        output=cancelled,
    )
    return st


def cancel_pending_ai_actions(reference_doctype, reference_name, include_reply_waits=True):
    """Withdraw queued AI work for this record.

    Spec §81's edge case: a workflow that is *waiting* to send later must be
    cancelled, not merely delayed -- otherwise it fires after the human has
    already replied.
    """
    filters = {
        "reference_doctype": reference_doctype,
        "reference_name": reference_name,
        "status": "Waiting",
    }
    if not include_reply_waits:
        # A contact's reply must not cancel the run that parked waiting for it.
        # A human taking over still cancels everything, which is the default.
        filters["waiting_for"] = ["!=", "Reply"]

    runs = frappe.get_all("Baton Workflow Run", filters=filters, pluck="name")
    for r in runs:
        frappe.db.set_value("Baton Workflow Run", r, {
            "status": "Cancelled",
            "resume_at": None,
            "resume_node": None,
            "cancelled_reason": "Human intervention -- AI follow-up withdrawn",
        })

    approvals = frappe.get_all(
        "Baton Approval",
        filters={
            "reference_doctype": reference_doctype,
            "reference_name": reference_name,
            "status": "Pending",
        },
        pluck="name",
    )
    for a in approvals:
        frappe.db.set_value("Baton Approval", a, {
            "status": "Expired",
            "resolved_by": frappe.session.user,
            "resolved_at": now_datetime(),
        })

    frappe.db.commit()
    return {"runs": len(runs), "approvals": len(approvals)}


def mark_ai_sent(reference_doctype, reference_name):
    st = get_state(reference_doctype, reference_name)
    st.last_ai_message_at = now_datetime()
    st.ai_turn_count = cint(st.ai_turn_count) + 1
    st.save(ignore_permissions=True)
    return st


def mark_inbound(reference_doctype, reference_name):
    """The contact replied. Reset the AI turn counter -- they are engaged."""
    st = get_state(reference_doctype, reference_name)
    st.last_inbound_at = now_datetime()
    st.ai_turn_count = 0
    st.save(ignore_permissions=True)
    return st


@frappe.whitelist()
def set_state(reference_doctype, reference_name, state, reason=None):
    """Manual override. Spec §29: the human always wins."""
    from baton.audit import log_action

    frappe.only_for(["System Manager", "Sales Manager", "Sales User"])
    st = get_state(reference_doctype, reference_name)
    previous = st.state
    st.state = state
    st.pause_reason = reason
    if state == "AI_ACTIVE":
        st.paused_until = None
    st.save(ignore_permissions=True)

    log_action("conversation.state_changed", actor_type="HUMAN",
               reference_doctype=reference_doctype, reference_name=reference_name,
               decision=state, reason=f"{previous} -> {state}. {reason or ''}".strip())
    return st.state


# ---------------------------------------------------------------- the gate

def can_ai_send(reference_doctype, reference_name, channel="WhatsApp"):
    """May the AI send on this record right now?

    Returns (allowed: bool, mode: str, reason: str) where mode is
    'Auto' or 'Draft'. Every refusal carries a human-readable reason, because
    spec §74 requires us to explain why a message was not sent.
    """
    settings = frappe.get_cached_doc("Baton Settings")

    if not settings.get("ai_enabled"):
        return False, "Off", "AI automation is switched off globally"

    mode = settings.get(
        "whatsapp_send_mode" if channel == "WhatsApp" else "email_send_mode"
    ) or "Draft"
    if mode == "Off":
        return False, "Off", f"{channel} automation is switched off"

    st = get_state(reference_doctype, reference_name, create=False)
    if st:
        if st.state == "DO_NOT_CONTACT":
            return False, mode, "Contact is marked do-not-contact"
        if st.state in SILENT_STATES:
            if st.paused_until and get_datetime(st.paused_until) > now_datetime():
                return False, mode, (
                    f"{st.state} until {st.paused_until} "
                    f"({st.pause_reason or 'paused'})"
                )
            if st.state != "HUMAN_ACTIVE":
                return False, mode, f"Conversation is {st.state}"

        turn_cap = cint(settings.get("ai_turn_cap") or 0)
        if turn_cap and cint(st.ai_turn_count) >= turn_cap:
            return False, mode, (
                f"AI has sent {st.ai_turn_count} consecutive messages "
                f"without a reply (cap {turn_cap})"
            )

    within, why = _within_quiet_hours(settings)
    if within:
        return False, mode, why

    ok, why = _within_rate_limit(settings, reference_doctype, reference_name)
    if not ok:
        return False, mode, why

    return True, mode, "allowed"


def _within_quiet_hours(settings):
    """Spec §51 -- postpone rather than fail, so the caller can reschedule."""
    if not settings.get("quiet_hours_enabled"):
        return False, ""
    start, end = settings.get("quiet_start"), settings.get("quiet_end")
    if not start or not end:
        return False, ""

    now = now_datetime().time()
    s, e = _as_time(start), _as_time(end)
    # A window like 22:00->08:00 wraps midnight.
    inside = (s <= now or now < e) if s > e else (s <= now < e)
    if inside:
        return True, f"Quiet hours ({s}-{e})"
    return False, ""


def _as_time(value):
    if hasattr(value, "seconds"):  # timedelta from a Time field
        total = int(value.total_seconds())
        import datetime
        return (datetime.datetime.min + datetime.timedelta(seconds=total)).time()
    if isinstance(value, str):
        import datetime
        return datetime.datetime.strptime(value.split(".")[0], "%H:%M:%S").time()
    return value


def _within_rate_limit(settings, reference_doctype, reference_name):
    """Spec §50 -- a cap on automated messages per record per day."""
    cap = cint(settings.get("max_messages_per_lead_per_day") or 0)
    if not cap:
        return True, ""
    since = add_to_date(now_datetime(), days=-1)
    sent = frappe.db.count("Baton Action Log", {
        "action": ["in", ["whatsapp.send", "email.send"]],
        "status": "Success",
        "reference_doctype": reference_doctype,
        "reference_name": reference_name,
        "creation": [">", since],
    })
    if sent >= cap:
        return False, f"Rate limit reached ({sent}/{cap} automated messages in 24h)"
    return True, ""


# ------------------------------------------------------------- cooldown job

def review_expired_cooldowns(limit=100):
    """Scheduler: act on conversations whose human cooldown has elapsed."""
    from baton.audit import log_action

    if not frappe.db.table_exists("Baton Conversation State"):
        return

    due = frappe.get_all(
        "Baton Conversation State",
        filters={"state": "HUMAN_ACTIVE", "paused_until": ["<=", now_datetime()]},
        fields=["name", "resume_policy", "reference_doctype", "reference_name"],
        limit_page_length=limit,
    )

    for row in due:
        policy = row.resume_policy or "REQUIRE_APPROVAL"
        if policy == "AUTO_RESUME":
            new_state, reason = "AI_ACTIVE", "Cooldown elapsed; auto-resumed"
        elif policy == "REQUIRE_APPROVAL":
            new_state, reason = "AI_REVIEW_PENDING", "Cooldown elapsed; awaiting human approval to resume"
        else:
            new_state, reason = "PAUSED", "Cooldown elapsed; policy is to remain paused"

        frappe.db.set_value("Baton Conversation State", row.name, {
            "state": new_state,
            "paused_until": None,
            "pause_reason": reason,
        })
        log_action("conversation.cooldown_expired", actor_type="SYSTEM",
                   reference_doctype=row.reference_doctype,
                   reference_name=row.reference_name,
                   decision=new_state, reason=reason)

    frappe.db.commit()
