"""Executes a Baton Workflow graph.

Design notes worth knowing before changing this file:

* **Runs are durable.** A `Wait` node persists `resume_at` on the run and
  returns; the scheduler wakes it later (spec §107). A workflow waiting three
  days holds no worker.
* **The run record is the source of truth.** Every node writes a step, and every
  externally-visible action writes a `Baton Action Log` row, so spec §74's "why
  didn't the AI send that message?" is answerable from CRM records alone. This
  is why execution state is not delegated to an external graph library.
* **Conditions are sandboxed.** `frappe.safe_eval`, never bare `eval`, so a
  workflow author cannot reach the filesystem or the database from a condition.
"""

import json
import re
import time

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

from baton.audit import already_done, log_action
from baton.conversation.state import can_ai_send

MAX_STEPS = 100  # cycle guard: a graph that loops would otherwise run forever

# Where run_workflow is enqueued, wherever it is enqueued from. A single AI Agent
# node is llm.DEFAULT_TIMEOUT (90s) with up to 3 chat_json retries, so a graph
# with two of them can legitimately exceed the "short" queue's 300s and get
# SIGKILLed part-way, leaving a half-written run nobody resumes.
RUN_QUEUE = "long"
RUN_TIMEOUT = 1500

# How long a wait-on-something-external lives before its timeout branch is
# taken. Every park has a deadline: a run that could wait forever is a run
# nobody ever finds out about.
DEFAULT_REPLY_TIMEOUT_HOURS = 24
DEFAULT_APPROVAL_TIMEOUT_HOURS = 48


class Park:
    """Returned by a node in place of a next-node id to suspend the run.

    `resume_node` is where the run continues when the wait is *satisfied* --
    for a reply-wait that is usually the parking node itself, so it can read
    what came back. `resume_node_alt` is where it goes when the deadline passes
    instead. Both are recorded on the run, so the scheduler can route a timeout
    without knowing anything about which node parked.
    """

    def __init__(self, waiting_for, seconds, resume_node,
                 resume_node_alt=None, channel="Any"):
        self.waiting_for = waiting_for
        self.seconds = max(int(seconds), 1)
        self.resume_node = resume_node
        self.resume_node_alt = resume_node_alt
        self.channel = channel


def _load_context(run):
    """Values carried across parks, addressable as `vars`."""
    if not run.get("context"):
        return {}
    try:
        return json.loads(run.context)
    except (json.JSONDecodeError, TypeError):
        return {}


def _save_context(run, vars_):
    # Capped because this round-trips through the DB on every node and is echoed
    # into prompts; an unbounded dict here becomes an unbounded token bill.
    run.context = json.dumps(vars_, default=str)[:8000]

# frappe.safe_eval whitelists only int/float/long/round, which is too thin to
# write a useful condition in. These additions are pure functions with no I/O,
# and RestrictedPython still guards attribute and subscript access on top.
SAFE_GLOBALS = {
    "bool": bool, "len": len, "str": str, "abs": abs, "min": min, "max": max,
    "any": any, "all": all, "sorted": sorted, "sum": sum, "set": set,
    "list": list, "dict": dict, "isinstance": isinstance,
}


def _eval(expression, doc, payload=None, vars_=None):
    # `vars` is whatever earlier nodes stashed via save_as, so a condition can
    # branch on something the graph worked out rather than only on the record.
    return frappe.safe_eval(
        expression,
        dict(SAFE_GLOBALS),
        {"doc": doc, "payload": payload or {}, "vars": vars_ or {}},
    )


def _cfg(node):
    if not node.config:
        return {}
    try:
        return json.loads(node.config)
    except (json.JSONDecodeError, TypeError):
        return {}


def _render(template, context):
    """Substitute {{ doc.field }} through Frappe's Jinja sandbox."""
    if not template or "{{" not in str(template):
        return template
    return frappe.render_template(str(template), context)


# ---------------------------------------------------------------- entrypoint

def run_workflow(
    workflow_name,
    doc=None,
    reference_doctype=None,
    reference_name=None,
    run_reason="manual",
    event_payload=None,
    resume_run=None,
    resume_at_node=None,
    resume_phase="enter",
    inbound_message=None,
):
    """Start a run, or continue one that was waiting.

    Returns the run name, or None when the workflow did not apply.
    """
    wf = frappe.get_doc("Baton Workflow", workflow_name)
    if not wf.enabled and run_reason != "test":
        return None

    # Resolve the subject document.
    if doc is None and reference_doctype and reference_name:
        if not frappe.db.exists(reference_doctype, reference_name):
            return None
        doc = frappe.get_doc(reference_doctype, reference_name)

    if resume_run:
        run = frappe.get_doc("Baton Workflow Run", resume_run)
        # The caller decides where to continue: the scheduler routes a timeout to
        # resume_node_alt, an inbound reply goes back to the node that parked.
        start_at = resume_at_node or run.resume_node
        if doc is None and run.reference_doctype and run.reference_name:
            if frappe.db.exists(run.reference_doctype, run.reference_name):
                doc = frappe.get_doc(run.reference_doctype, run.reference_name)
        run.status = "Running"
        run.resume_at = None
        run.resume_node = None
        run.resume_node_alt = None
        run.waiting_for = None
        run.waiting_channel = None
    else:
        if wf.condition and not _eval(wf.condition, doc, event_payload):
            return None
        run = frappe.get_doc({
            "doctype": "Baton Workflow Run",
            "workflow": wf.name,
            "status": "Running",
            "reference_doctype": doc.doctype if doc else None,
            "reference_name": doc.name if doc else None,
        }).insert(ignore_permissions=True)
        start_at = None

    run.run_reason = run_reason

    payload = dict(event_payload or {})
    if inbound_message:
        payload["inbound"] = _inbound_payload(inbound_message)

    vars_ = _load_context(run)
    context = {"doc": doc, "payload": payload, "vars": vars_}
    nodes = {n.node_id: n for n in wf.nodes}

    # Only the first node of a resumed run sees the "reply" phase; everything
    # downstream of it is an ordinary entry.
    phase = resume_phase if resume_run else "enter"

    current = start_at
    if current is None:
        trigger = next((n.node_id for n in wf.nodes if n.node_type == "Trigger"), None)
        current = trigger or (wf.nodes[0].node_id if wf.nodes else None)

    _emit_lifecycle("workflow.started", wf, run)

    steps = 0
    try:
        while current and steps < MAX_STEPS:
            node = nodes.get(current)
            if not node:
                break
            steps += 1

            outcome, next_id, status = _execute_with_retry(node, context, run, wf, phase)
            phase = "enter"  # consumed; only the resumed node gets a special phase

            # The node itself ran fine, but it did not do the thing it exists to
            # do. Recording that as Success makes a suppressed send look
            # identical to a delivered one when someone scans the run.
            if status == "Success" and (outcome.get("skipped") or outcome.get("blocked")):
                status = "Skipped"
            _append_step(run, node, status, outcome, outcome.pop("_ms", 0))

            if node.save_as and status == "Success":
                vars_[node.save_as] = outcome.get("result", outcome)

            # --- the node asked to be suspended ------------------------------
            if isinstance(next_id, Park):
                _save_context(run, vars_)
                _park(run, node, next_id)
                return run.name

            # Each node is its own durable unit. Without this a crash part-way
            # through rolls the whole transaction back, so a run that really did
            # send two messages leaves no step trace at all -- which breaks the
            # one thing the audit trail exists to answer. The heartbeat rides
            # along on the same write so it costs nothing extra; sweep_stale_runs
            # uses it to tell a working run from an abandoned one.
            _save_context(run, vars_)
            run.heartbeat_at = now_datetime()
            run.save(ignore_permissions=True)
            frappe.db.commit()

            if status == "Failed" and node.on_error == "Fail run":
                run.status = "Failed"
                run.error = json.dumps(outcome, default=str)[:4000]
                break

            current = next_id

        else:
            if steps >= MAX_STEPS:
                run.status = "Failed"
                run.error = f"Stopped after {MAX_STEPS} steps -- the graph probably loops."

        if run.status == "Running":
            run.status = "Completed"

    except Exception:
        run.status = "Failed"
        run.error = frappe.get_traceback()[:4000]
        frappe.log_error(title=f"Baton workflow {wf.name} failed", message=frappe.get_traceback())
    finally:
        run.save(ignore_permissions=True)
        frappe.db.commit()

    _emit_lifecycle(
        "workflow.completed" if run.status == "Completed" else "workflow.failed",
        wf, run)
    return run.name


ORDINALS = {"first": 1, "second": 2, "third": 3, "one": 1, "two": 2, "three": 3}


def _pick_slot(reply, offered):
    """Which offered slot did they mean? Deliberately no model involved.

    A regex cannot hallucinate a time that was never offered, and "reply with a
    number" is the whole reason the numbered format was chosen.
    """
    if not offered:
        return None
    text = (reply or "").strip().lower()
    if not text:
        return None

    leading = re.match(r"^\D{0,3}(\d{1,2})\b", text)
    if leading:
        index = int(leading.group(1))
        if 1 <= index <= len(offered):
            return offered[index - 1]

    for word, index in ORDINALS.items():
        if re.search(rf"\b{word}\b", text) and index <= len(offered):
            return offered[index - 1]

    # An unambiguous clock time they typed back at us.
    clock = re.findall(r"\b(\d{1,2}):(\d{2})\b", text)
    if len(clock) == 1:
        hh, mm = int(clock[0][0]), int(clock[0][1])
        matches = [s for s in offered
                   if get_datetime(s).hour == hh and get_datetime(s).minute == mm]
        if len(matches) == 1:
            return matches[0]
    return None


def _slot_list(slots, availability):
    from baton.scheduling import workhours as wh

    tz = wh.tz_of(availability)
    return "\n".join(f"{i}. {wh.label(s, tz)}" for i, s in enumerate(slots, start=1))


def _emit_lifecycle(event, wf, run):
    """Announce a run starting or ending.

    These three events have been declared in baton.events.EVENTS from the start
    and never emitted, so nothing could observe a run without polling. They are
    observability only -- a workflow may not subscribe to workflow.* (see
    events.emit), because a workflow that triggers on its own completion is a
    loop with extra steps.
    """
    try:
        from baton.events import emit

        emit(event,
             reference_doctype=run.reference_doctype,
             reference_name=run.reference_name,
             payload={"workflow": wf.name, "run": run.name, "status": run.status})
    except Exception:
        # Never let telemetry fail a run.
        frappe.log_error(title=f"Baton: could not emit {event}")


# What the condition picker offers, and how each maps onto an expression. Kept
# here rather than in the UI so the builder cannot offer an operator the engine
# does not implement.
RULE_OPERATORS = {
    "is": "{lhs} == {rhs}",
    "is not": "{lhs} != {rhs}",
    "contains": "{rhs} in str({lhs} or '')",
    "does not contain": "{rhs} not in str({lhs} or '')",
    "is set": "bool({lhs})",
    "is not set": "not bool({lhs})",
    "greater than": "({lhs} or 0) > {rhs}",
    "less than": "({lhs} or 0) < {rhs}",
}


def _rules_to_expression(rules):
    """Compile [{field, operator, value}] into one safe_eval expression."""
    if not rules:
        return None
    if isinstance(rules, str):
        try:
            rules = json.loads(rules)
        except (json.JSONDecodeError, TypeError):
            return None

    parts = []
    for rule in rules:
        field = (rule or {}).get("field")
        operator = (rule or {}).get("operator")
        if not field or operator not in RULE_OPERATORS:
            continue
        # Field names come from get_fields, but this is the boundary where a
        # crafted config could inject -- so allow only identifier-ish names.
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field):
            continue
        source = "vars" if str(rule.get("source")) == "vars" else "doc"
        lhs = f"{source}.get({field!r})" if source == "vars" else f"doc.{field}"
        # repr() so the value is always a literal, never fragments of expression.
        parts.append(RULE_OPERATORS[operator].format(
            lhs=lhs, rhs=repr(rule.get("value"))))

    return " and ".join(parts) if parts else None


def _turn(run, node_id):
    """How many times this run has entered this node.

    Idempotency keys include it, because a conversation node re-enters itself on
    every customer reply and would otherwise collide with its own first send.
    """
    vars_ = _load_context(run)
    return int((vars_.get("_turns") or {}).get(node_id, 0))


def _bump_turn(vars_, node_id):
    turns = vars_.setdefault("_turns", {})
    turns[node_id] = int(turns.get(node_id, 0)) + 1
    return turns[node_id]


def _park(run, node, park):
    """Suspend a run until its wait is satisfied or its deadline passes.

    Every park sets resume_at, including one waiting on a customer. That is what
    stops a conversation stalling silently forever when nobody replies: the
    scheduler will take resume_node_alt when the deadline arrives.
    """
    now = now_datetime()

    # Two agents parked on the same conversation would talk over each other, so
    # a new reply-wait supersedes any older one on the same record and channel.
    if park.waiting_for == "Reply" and run.reference_doctype and run.reference_name:
        others = frappe.get_all(
            "Baton Workflow Run",
            filters={
                "name": ["!=", run.name],
                "status": "Waiting",
                "waiting_for": "Reply",
                "reference_doctype": run.reference_doctype,
                "reference_name": run.reference_name,
            },
            pluck="name",
        )
        for other in others:
            frappe.db.set_value("Baton Workflow Run", other, {
                "status": "Cancelled",
                "resume_at": None,
                "resume_node": None,
                "cancelled_reason": "Superseded by a newer conversation step",
            })
            log_action("run.superseded", reference_doctype=run.reference_doctype,
                       reference_name=run.reference_name, workflow_run=other,
                       reason=f"Replaced by {run.name}")

    run.status = "Waiting"
    run.waiting_for = park.waiting_for
    run.waiting_channel = park.channel
    run.waiting_since = now
    run.resume_at = add_to_date(now, seconds=park.seconds)
    run.resume_node = park.resume_node
    run.resume_node_alt = park.resume_node_alt
    run.heartbeat_at = now
    run.save(ignore_permissions=True)
    frappe.db.commit()


def _inbound_payload(message_name):
    """The customer's message, as a node sees it on the reply phase."""
    msg = frappe.db.get_value(
        "WhatsApp Message", message_name,
        ["name", "message", "creation", "baton_author"], as_dict=True,
    )
    if not msg:
        return {}
    return {
        "name": msg.name,
        "text": (msg.message or "").strip(),
        "channel": "WhatsApp",
        "at": str(msg.creation),
        "author": msg.baton_author,
    }


def _wait_seconds(cfg):
    unit = (cfg.get("unit") or "minutes").lower()
    amount = cint(cfg.get("amount") or cfg.get("minutes") or 0)
    factor = {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400}.get(unit, 60)
    return max(amount * factor, 1)


def _append_step(run, node, status, output, ms):
    run.append("steps", {
        "node_id": node.node_id,
        "node_type": node.node_type,
        "status": status,
        "duration_ms": ms,
        "output": json.dumps(output, default=str)[:4000],
    })


def _execute_with_retry(node, context, run, wf, phase="enter"):
    """Run one node, honouring its retry policy. Returns (outcome, next_id, status)."""
    attempts = cint(node.max_retries) + 1
    delay = cint(node.retry_delay) or 30
    last_error = None

    for attempt in range(1, attempts + 1):
        started = time.time()
        try:
            outcome, next_id = _execute(node, context, run, phase)
            outcome["_ms"] = int((time.time() - started) * 1000)
            log_action(
                f"node.{node.node_type}",
                actor_type="AI_AGENT" if node.node_type == "AI Agent" else "SYSTEM",
                reference_doctype=run.reference_doctype,
                reference_name=run.reference_name,
                workflow=wf.name,
                workflow_run=run.name,
                node_id=node.node_id,
                output=outcome,
                latency_ms=outcome["_ms"],
            )
            return outcome, next_id, "Success"
        except Exception as e:
            last_error = str(e)
            log_action(
                f"node.{node.node_type}",
                status="Failed",
                reference_doctype=run.reference_doctype,
                reference_name=run.reference_name,
                workflow=wf.name,
                workflow_run=run.name,
                node_id=node.node_id,
                error=last_error,
                latency_ms=int((time.time() - started) * 1000),
                reason=f"attempt {attempt} of {attempts}",
            )
            if attempt < attempts:
                time.sleep(min(delay * (2 ** (attempt - 1)), 30))  # capped backoff

    outcome = {"error": last_error, "attempts": attempts, "_ms": 0}
    if node.on_error == "Continue":
        return outcome, node.next_node, "Failed"
    if node.on_error == "Go to fallback":
        return outcome, node.fallback_node, "Failed"
    return outcome, None, "Failed"


# ------------------------------------------------------------------- actions

def _execute(node, context, run, phase="enter"):
    """Run one node.

    Returns (outcome_dict, next_node_id), where next_node_id may be a `Park`
    asking for the run to be suspended.

    `phase` is "enter" normally. A node that parked on a customer reply is
    re-entered with phase="reply" and finds the message in
    context["payload"]["inbound"].
    """
    cfg = _cfg(node)
    doc = context.get("doc")
    payload = context.get("payload")
    kind = node.node_type

    if kind == "Trigger":
        return {"ok": True}, node.next_node

    if kind == "Wait":
        seconds = _wait_seconds(cfg)
        return ({"waiting_seconds": seconds},
                Park("Timer", seconds, resume_node=node.next_node))

    if kind == "AI Conversation":
        from baton.agents import conversation as convo
        from baton.workflow.actions import whatsapp as wa_action

        agent_name = cfg.get("agent")
        if not agent_name:
            return {"skipped": "no agent configured"}, node.next_node_alt or node.next_node

        agent = frappe.get_cached_doc("Baton Agent", agent_name)
        vars_ = context.setdefault("vars", {})
        turn = _bump_turn(vars_, node.node_id)

        # A per-node cap on top of Baton Settings' per-conversation ai_turn_cap:
        # this one stops a single step looping, that one stops the AI dominating
        # the whole thread.
        if turn > (cint(agent.max_turns) or 6):
            return ({"stopped": "max turns reached", "turns": turn},
                    node.next_node_alt or node.next_node)

        known = {k: v for k, v in vars_.items() if not str(k).startswith("_")}
        decision = convo.decide(agent_name, doc.doctype if doc else None,
                                doc.name if doc else None, known=known,
                                run=run, node_id=node.node_id)

        vars_.update(decision["facts"])
        if decision["choice"]:
            vars_.setdefault("service", decision["choice"])
        if doc and decision["facts"]:
            convo.apply_facts(agent_name, doc.doctype, doc.name, decision["facts"])

        if decision["action"] == "handoff":
            from baton.conversation.state import set_state

            if doc:
                set_state(doc.doctype, doc.name, "ESCALATED",
                          reason=decision["reason"] or "Agent handed over")
            return ({"action": "handoff", "reason": decision["reason"]},
                    node.next_node_alt or node.next_node)

        if decision["action"] == "finish":
            return ({"action": "finish", "facts": decision["facts"],
                     "choice": decision["choice"], "result": decision["choice"]},
                    node.next_node)

        # ask: say it through the one gated send path, then wait for them.
        outcome = wa_action.send(
            to=_render(cfg.get("to"), context),
            message=decision["message"],
            run=run, node=node, doc=doc, author="ai", turn=turn,
        )
        if outcome.get("blocked"):
            # Refused by the gate. Do not re-prompt -- park and let the deadline
            # decide, or let a human take it from here.
            return ({"action": "ask", "blocked": outcome.get("skipped")},
                    Park("Reply", (cint(agent.reply_timeout_hours) or 24) * 3600,
                         resume_node=node.node_id,
                         resume_node_alt=node.next_node_alt,
                         channel=agent.channel or "WhatsApp"))

        return ({"action": "ask", "message": decision["message"], **outcome},
                Park("Reply", (cint(agent.reply_timeout_hours) or 24) * 3600,
                     resume_node=node.node_id,
                     resume_node_alt=node.next_node_alt,
                     channel=agent.channel or "WhatsApp"))

    if kind == "Offer Slots":
        from baton.scheduling import book as booking
        from baton.scheduling import slots as slot_mod
        from baton.scheduling import workhours as wh
        from baton.workflow.actions import whatsapp as wa_action

        vars_ = context.setdefault("vars", {})
        service_name = cfg.get("service")
        service = (frappe.get_cached_doc("Baton Service", service_name)
                   if service_name and frappe.db.exists("Baton Service", service_name)
                   else None)
        availability = slot_mod.resolve_availability(
            doc.doctype if doc else None, doc.name if doc else None,
            service=service_name, explicit=cfg.get("availability"))
        if not availability:
            return ({"skipped": "no availability configured"},
                    node.next_node_alt or node.next_node)

        count = cint(cfg.get("count")) or 3
        duration = cint(service.duration_minutes if service else 0) or cint(cfg.get("duration")) or 30

        # --- reply: they picked one -------------------------------------
        if phase == "reply":
            offered = vars_.get("offered_slots") or []
            reply = ((context.get("payload") or {}).get("inbound") or {}).get("text", "")
            picked = _pick_slot(reply, offered)

            if picked is None:
                turn = _bump_turn(vars_, node.node_id)
                if turn > (cint(cfg.get("max_reprompts")) or 1) + 1:
                    return ({"gave_up": "unparseable reply", "reply": reply[:200]},
                            node.next_node_alt or node.next_node)
                wa_action.send(
                    to=_render(cfg.get("to"), context),
                    message=_("Sorry, I didn't catch that — just reply with 1, 2 or 3."),
                    run=run, node=node, doc=doc, author="ai", turn=turn,
                )
                return ({"reprompted": True},
                        Park("Reply", (cint(cfg.get("timeout_hours")) or 24) * 3600,
                             resume_node=node.node_id,
                             resume_node_alt=node.next_node_alt, channel="WhatsApp"))

            start = get_datetime(picked)
            end = add_to_date(start, minutes=duration)
            held, why = booking.hold(
                availability.user, start, end,
                reference_doctype=doc.doctype if doc else None,
                reference_name=doc.name if doc else None,
                service=service_name, workflow_run=run.name)

            if not held:
                # Taken between offering and answering. Apologise and re-offer
                # rather than silently failing.
                fresh = slot_mod.free_slots(availability, duration, limit=count,
                                            user=availability.user)[:count]
                if not fresh:
                    return ({"skipped": why}, node.next_node_alt or node.next_node)
                vars_["offered_slots"] = [str(s) for s in fresh]
                wa_action.send(
                    to=_render(cfg.get("to"), context),
                    message=_("Sorry, {0} just went. Here are the next available times:").format(
                        wh.label(start, wh.tz_of(availability)))
                    + "\n" + _slot_list(fresh, availability),
                    run=run, node=node, doc=doc, author="ai",
                    turn=_bump_turn(vars_, node.node_id),
                )
                return ({"reoffered": True, "reason": why},
                        Park("Reply", (cint(cfg.get("timeout_hours")) or 24) * 3600,
                             resume_node=node.node_id,
                             resume_node_alt=node.next_node_alt, channel="WhatsApp"))

            vars_["booking_hold"] = held.name
            vars_["slot_start"] = str(start)
            vars_["slot_label"] = wh.label(start, wh.tz_of(availability))
            return ({"held": held.name, "slot": str(start), "result": str(start)},
                    node.next_node)

        # --- enter: offer what is free ----------------------------------
        available = slot_mod.free_slots(availability, duration, limit=count,
                                        user=availability.user)[:count]
        if not available:
            return ({"skipped": "no free slots in the window"},
                    node.next_node_alt or node.next_node)

        vars_["offered_slots"] = [str(s) for s in available]
        outcome = wa_action.send(
            to=_render(cfg.get("to"), context),
            message=(_render(cfg.get("message"), context)
                     or _("When suits you? Reply with a number."))
            + "\n" + _slot_list(available, availability),
            run=run, node=node, doc=doc, author="ai",
            turn=_bump_turn(vars_, node.node_id),
        )
        if outcome.get("blocked"):
            return ({"blocked": outcome.get("skipped")},
                    node.next_node_alt or node.next_node)

        return ({"offered": vars_["offered_slots"], **outcome},
                Park("Reply", (cint(cfg.get("timeout_hours")) or 24) * 3600,
                     resume_node=node.node_id,
                     resume_node_alt=node.next_node_alt, channel="WhatsApp"))

    if kind == "Book Appointment":
        from baton.scheduling import book as booking
        from baton.workflow.actions import whatsapp as wa_action

        vars_ = context.setdefault("vars", {})
        hold_name = vars_.get("booking_hold")
        if not hold_name or not frappe.db.exists("Baton Booking Hold", hold_name):
            return ({"skipped": "no held slot"}, node.next_node_alt or node.next_node)

        held = frappe.get_doc("Baton Booking Hold", hold_name)
        key = f"booking:{run.name}:{node.node_id}"
        if already_done(key):
            return {"skipped": "already booked (idempotency)"}, node.next_node

        availability = frappe.get_doc("Baton Availability",
                                      cfg.get("availability")) if cfg.get("availability") else None
        subject = (_render(cfg.get("subject"), context)
                   or _("Call with {0}").format(doc.get("lead_name") if doc else "customer"))

        event = booking.confirm(
            held, subject=subject,
            description=_render(cfg.get("description"), context),
            google_calendar=(availability.google_calendar if availability else None),
            add_video=cfg.get("add_video"),
        )
        log_action("booking.confirm", reference_doctype=held.reference_doctype,
                   reference_name=held.reference_name, workflow_run=run.name,
                   node_id=node.node_id, idempotency_key=key, external_id=event)

        video_url = booking.video_link(event)
        vars_["video_url"] = video_url

        confirmation = (_render(cfg.get("confirmation"), context)
                        or _("Booked — {0}. See you then.").format(vars_.get("slot_label", "")))
        if video_url and video_url not in confirmation:
            confirmation = f"{confirmation}\n{_('Join')}: {video_url}"
        wa_action.send(to=_render(cfg.get("to"), context), message=confirmation,
                       run=run, node=node, doc=doc, author="ai", turn=0)

        vars_["event"] = event
        return {"event": event, "result": event, "video_url": video_url}, node.next_node

    if kind == "Await Reply":
        # Enter: park until the contact says something on this channel.
        # Reply: hand what they said to the branch, and stash it for later nodes.
        channel = cfg.get("channel") or "WhatsApp"
        if phase != "reply":
            hours = cint(cfg.get("timeout_hours")) or DEFAULT_REPLY_TIMEOUT_HOURS
            return ({"awaiting": channel, "timeout_hours": hours},
                    Park("Reply", hours * 3600, resume_node=node.node_id,
                         resume_node_alt=node.next_node_alt, channel=channel))

        inbound = (context.get("payload") or {}).get("inbound") or {}
        text = inbound.get("text", "")
        context.setdefault("vars", {})["last_reply"] = text
        return ({"result": text, "replied": True, "message": inbound.get("name")},
                node.next_node)

    if kind == "Condition":
        # Rules built in the UI are compiled to the same sandboxed expression the
        # code path uses, so there is one evaluator and one set of guarantees.
        # A hand-written expression wins, because someone who wrote one meant it.
        expr = cfg.get("expression") or _rules_to_expression(cfg.get("rules")) or "True"
        result = bool(_eval(expr, doc, payload, context.get("vars")))
        return ({"expression": expr, "result": result},
                node.next_node if result else node.next_node_alt)

    if kind == "Update Field":
        if not doc:
            return {"skipped": "no document in context"}, node.next_node
        # The palette entry said which record type it was written for. Writing a
        # deal's field onto a lead because the names happened to collide is
        # worse than doing nothing and saying why.
        wants = cfg.get("for_doctype")
        if wants and wants != doc.doctype:
            return ({"skipped": f"written for a {wants}, but this run is on a {doc.doctype}"},
                    node.next_node)
        field, value = cfg.get("field"), _render(cfg.get("value"), context)
        if not field:
            return {"skipped": "no field chosen"}, node.next_node
        if not doc.meta.has_field(field):
            return {"skipped": f"{doc.doctype} has no field '{field}'"}, node.next_node
        frappe.db.set_value(doc.doctype, doc.name, field, value)
        return {"field": field, "value": value}, node.next_node

    if kind == "Create Document":
        target = cfg.get("doctype")
        values = {k: _render(v, context) for k, v in (cfg.get("values") or {}).items()}
        created = frappe.get_doc({"doctype": target, **values}).insert(ignore_permissions=True)
        return {"created": created.name, "doctype": target}, node.next_node

    if kind == "Send WhatsApp":
        from baton.workflow.actions import whatsapp as wa_action

        return wa_action.send(
            to=_render(cfg.get("to"), context),
            message=_render(cfg.get("message"), context),
            run=run, node=node, doc=doc,
            author=cfg.get("author") or "ai",
            template=cfg.get("template"),
            turn=_turn(run, node.node_id),
        ), node.next_node

    if kind == "Send Email":
        key = f"email:{run.name}:{node.node_id}"
        if already_done(key):
            return {"skipped": "already sent (idempotency)"}, node.next_node

        # Same gate as WhatsApp, with email's own send mode (drafted by default).
        if doc:
            allowed, mode, why = can_ai_send(doc.doctype, doc.name, channel="Email")
            if not allowed:
                log_action("email.send", status="Skipped", actor_type="AI_AGENT",
                           reference_doctype=doc.doctype, reference_name=doc.name,
                           workflow_run=run.name, node_id=node.node_id,
                           decision="SUPPRESSED", reason=why)
                return {"skipped": why}, node.next_node
            if mode == "Draft":
                approval = frappe.get_doc({
                    "doctype": "Baton Approval",
                    "kind": "Send Message",
                    "status": "Pending",
                    "draft_text": _render(cfg.get("message"), context),
                    "reference_doctype": doc.doctype,
                    "reference_name": doc.name,
                    "payload": json.dumps(
                        {"to": _render(cfg.get("to"), context),
                         "subject": _render(cfg.get("subject"), context),
                         "channel": "Email"}, default=str),
                }).insert(ignore_permissions=True)
                log_action("email.draft", actor_type="AI_AGENT",
                           reference_doctype=doc.doctype, reference_name=doc.name,
                           workflow_run=run.name, node_id=node.node_id,
                           decision="AWAIT_APPROVAL", reason="Draft mode is on for email",
                           output={"approval": approval.name})
                return {"drafted": approval.name}, node.next_node

        recipient = _render(cfg.get("to"), context)
        try:
            frappe.flags.baton_ai_email = True
            frappe.sendmail(
                recipients=[recipient],
                subject=_render(cfg.get("subject"), context) or "(no subject)",
                message=_render(cfg.get("message"), context) or "",
                reference_doctype=doc.doctype if doc else None,
                reference_name=doc.name if doc else None,
            )
        finally:
            frappe.flags.baton_ai_email = False
        log_action("email.send", reference_doctype=doc.doctype if doc else None,
                   reference_name=doc.name if doc else None, workflow_run=run.name,
                   node_id=node.node_id, idempotency_key=key, output={"to": recipient})
        return {"queued": True, "to": recipient}, node.next_node

    if kind == "Request Approval":
        approval = frappe.get_doc({
            "doctype": "Baton Approval",
            "kind": cfg.get("kind") or "Other",
            "status": "Pending",
            "draft_text": _render(cfg.get("draft"), context),
            "reference_doctype": doc.doctype if doc else None,
            "reference_name": doc.name if doc else None,
            "payload": json.dumps(cfg, default=str),
        }).insert(ignore_permissions=True)
        # An approval is a genuine pause -- but it used to set status/resume_node
        # without a resume_at, and resume_due_runs only looks at runs with one.
        # Nothing ever resumed it. It now parks like everything else, so an
        # approval nobody acts on eventually takes the reject branch instead of
        # stalling the run forever.
        hours = cint(cfg.get("timeout_hours")) or DEFAULT_APPROVAL_TIMEOUT_HOURS
        frappe.db.set_value("Baton Approval", approval.name, {
            "workflow_run": run.name,
            "expires_at": add_to_date(now_datetime(), hours=hours),
        }, update_modified=False)
        return ({"approval": approval.name, "timeout_hours": hours},
                Park("Approval", hours * 3600, resume_node=node.next_node,
                     resume_node_alt=node.next_node_alt))

    if kind == "AI Agent":
        from baton.llm import chat

        prompt = _render(cfg.get("prompt"), context) or ""
        purpose = cfg.get("purpose") or "Workflow"
        reply = chat([{"role": "user", "content": prompt}], purpose=purpose)
        return {"reply": reply[:2000], "purpose": purpose}, node.next_node

    if kind == "Check Reply":
        # Has the contact replied since our last outbound? This is what stops a
        # ladder dead the moment someone engages (spec §17).
        from baton.conversation.thread import get_conversation

        if not doc:
            return {"replied": False, "reason": "no document"}, node.next_node_alt
        channel = cfg.get("channel") or "Any"
        msgs = [m for m in get_conversation(doc.doctype, doc.name)
                if channel == "Any" or m.get("channel") == channel]
        last_in = next((m["timestamp"] for m in reversed(msgs)
                        if m["direction"] == "incoming"), None)
        last_out = next((m["timestamp"] for m in reversed(msgs)
                         if m["direction"] == "outgoing"), None)
        replied = bool(last_in and (not last_out or last_in > last_out))
        return ({"replied": replied, "last_inbound": str(last_in),
                 "last_outbound": str(last_out)},
                node.next_node if replied else node.next_node_alt)

    if kind == "Create Task":
        if not doc:
            return {"skipped": "no document in context"}, node.next_node
        owner = cfg.get("owner") or frappe.session.user
        task = frappe.get_doc({
            "doctype": "CRM Task",
            "title": _render(cfg.get("subject"), context) or "Follow up",
            "description": _render(cfg.get("description"), context) or "",
            "reference_doctype": doc.doctype,
            "reference_docname": doc.name,
            "assigned_to": owner,
            "status": "Backlog",
            "priority": cfg.get("priority") or "Medium",
        }).insert(ignore_permissions=True)
        log_action("task.create", reference_doctype=doc.doctype, reference_name=doc.name,
                   workflow_run=run.name, node_id=node.node_id,
                   output={"task": task.name}, reason="Automated follow-ups exhausted")
        return {"task": task.name}, node.next_node

    if kind == "Assign To":
        if not doc:
            return {"skipped": "no document in context"}, node.next_node
        # _add rather than add: the public one calls check_permission against the
        # session user, and a run started by a webhook or the scheduler has no
        # business failing because of whose session it happened to inherit.
        from frappe.desk.form.assign_to import _add as assign_add

        user = (_render(cfg.get("assign_to"), context)
                or doc.get("lead_owner") or doc.get("deal_owner") or doc.owner)
        if not user or not frappe.db.exists("User", user):
            return {"skipped": f"no such user: {user}"}, node.next_node

        # Already on their list. Checked here rather than caught, because
        # assign_to reports a duplicate with a msgprint and no exception -- so
        # an `except` around it would never fire. Re-running a workflow should
        # converge on the state it describes, not raise.
        if frappe.db.exists("ToDo", {"reference_type": doc.doctype,
                                     "reference_name": doc.name,
                                     "allocated_to": user, "status": "Open"}):
            return {"skipped": "already assigned", "assigned_to": user}, node.next_node

        assign_add({
            "doctype": doc.doctype, "name": doc.name, "assign_to": [user],
            "description": _render(cfg.get("description"), context)
            or f"{doc.doctype} {doc.name}",
        }, ignore_permissions=True)
        log_action("assign", reference_doctype=doc.doctype, reference_name=doc.name,
                   workflow_run=run.name, node_id=node.node_id, output={"user": user})
        return {"assigned_to": user}, node.next_node

    if kind == "Add Comment":
        if not doc:
            return {"skipped": "no document in context"}, node.next_node
        text = _render(cfg.get("comment"), context)
        if not (text or "").strip():
            return {"skipped": "nothing to say"}, node.next_node
        comment = frappe.get_doc(doc.doctype, doc.name).add_comment("Comment", text)
        return {"comment": comment.name}, node.next_node

    if kind == "Create Note":
        if not doc:
            return {"skipped": "no document in context"}, node.next_node
        note = frappe.get_doc({
            "doctype": "FCRM Note",
            "title": _render(cfg.get("title"), context) or "Note",
            "content": _render(cfg.get("content"), context) or "",
            "reference_doctype": doc.doctype,
            "reference_docname": doc.name,
        }).insert(ignore_permissions=True)
        return {"note": note.name}, node.next_node

    if kind == "Convert Lead":
        if not doc or doc.doctype != "CRM Lead":
            return ({"skipped": "this step only works on a lead"},
                    node.next_node_alt or node.next_node)
        if doc.get("converted"):
            return {"skipped": "already converted"}, node.next_node
        from crm.fcrm.doctype.crm_lead.crm_lead import convert_to_deal

        lead = frappe.get_doc("CRM Lead", doc.name)
        lead.flags.ignore_permissions = True
        deal = convert_to_deal(lead=doc.name, doc=lead)
        log_action("lead.convert", reference_doctype="CRM Lead", reference_name=doc.name,
                   workflow_run=run.name, node_id=node.node_id, output={"deal": deal})
        context.setdefault("vars", {})["deal"] = deal
        return {"deal": deal, "result": deal}, node.next_node

    if kind == "Webhook":
        import requests

        resp = requests.post(cfg.get("url"), json=cfg.get("body") or {}, timeout=20)
        return {"status_code": resp.status_code}, node.next_node

    return {"unhandled": kind}, node.next_node


# ------------------------------------------------------------------ triggers

def handle_document_event(doc, method):
    """Fan a Frappe doc event out to any workflow listening for it."""
    if getattr(frappe.flags, "in_install", False) or getattr(frappe.flags, "in_migrate", False):
        return
    if not frappe.db.table_exists("Baton Workflow"):
        return

    if not frappe.db.table_exists("Baton Workflow Trigger"):
        return

    # Frappe runs on_update during insert as well, so a workflow listening for
    # both events would fire twice on creation -- and send the greeting twice.
    # after_insert owns creation; on_update means "changed afterwards".
    if method == "on_update" and getattr(doc.flags, "in_insert", False):
        return

    rows = frappe.get_all(
        "Baton Workflow Trigger",
        filters={
            "parenttype": "Baton Workflow",
            "enabled": 1,
            "trigger_type": "Document Event",
            "trigger_doctype": doc.doctype,
            "trigger_event": method,
        },
        fields=["parent", "field_changed", "condition"],
    )
    if not rows:
        return

    enabled = set(frappe.get_all(
        "Baton Workflow",
        filters={"name": ["in", list({r.parent for r in rows})], "enabled": 1},
        pluck="name",
    ))

    names = []
    for r in rows:
        if r.parent not in enabled or r.parent in names:
            continue
        # "only when this field changes" is what makes an on_update trigger
        # usable at all -- otherwise every unrelated save fires the workflow.
        if r.field_changed and not doc.has_value_changed(r.field_changed):
            continue
        if r.condition:
            try:
                if not _eval(r.condition, doc):
                    continue
            except Exception:
                frappe.log_error(title=f"Baton trigger condition failed for {r.parent}")
                continue
        names.append(r.parent)

    for name in names:
        frappe.enqueue(
            "baton.workflow.engine.run_workflow",
            queue=RUN_QUEUE,
            timeout=RUN_TIMEOUT,
            workflow_name=name,
            reference_doctype=doc.doctype,
            reference_name=doc.name,
            run_reason=method,
        )


@frappe.whitelist()
def run_now(workflow_name, reference_doctype=None, reference_name=None):
    """Fire a workflow by hand -- the Test button in the builder."""
    frappe.only_for(["System Manager", "Sales Manager"])
    return run_workflow(
        workflow_name,
        reference_doctype=reference_doctype,
        reference_name=reference_name,
        run_reason="manual",
    )
