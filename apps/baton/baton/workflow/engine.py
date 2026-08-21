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
import time

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, now_datetime

from baton.audit import already_done, log_action
from baton.conversation.state import can_ai_send

MAX_STEPS = 100  # cycle guard: a graph that loops would otherwise run forever

# frappe.safe_eval whitelists only int/float/long/round, which is too thin to
# write a useful condition in. These additions are pure functions with no I/O,
# and RestrictedPython still guards attribute and subscript access on top.
SAFE_GLOBALS = {
    "bool": bool, "len": len, "str": str, "abs": abs, "min": min, "max": max,
    "any": any, "all": all, "sorted": sorted, "sum": sum, "set": set,
    "list": list, "dict": dict, "isinstance": isinstance,
}


def _eval(expression, doc, payload=None):
    return frappe.safe_eval(
        expression, dict(SAFE_GLOBALS), {"doc": doc, "payload": payload or {}}
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
        start_at = run.resume_node
        if doc is None and run.reference_doctype and run.reference_name:
            if frappe.db.exists(run.reference_doctype, run.reference_name):
                doc = frappe.get_doc(run.reference_doctype, run.reference_name)
        run.status = "Running"
        run.resume_at = None
        run.resume_node = None
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

    context = {"doc": doc, "payload": event_payload or {}}
    nodes = {n.node_id: n for n in wf.nodes}

    current = start_at
    if current is None:
        trigger = next((n.node_id for n in wf.nodes if n.node_type == "Trigger"), None)
        current = trigger or (wf.nodes[0].node_id if wf.nodes else None)

    steps = 0
    try:
        while current and steps < MAX_STEPS:
            node = nodes.get(current)
            if not node:
                break
            steps += 1

            # --- durable wait: persist and hand back to the scheduler --------
            if node.node_type == "Wait":
                cfg = _cfg(node)
                seconds = _wait_seconds(cfg)
                run.status = "Waiting"
                run.resume_at = add_to_date(now_datetime(), seconds=seconds)
                run.resume_node = node.next_node
                _append_step(run, node, "Success",
                             {"waiting_seconds": seconds, "resume_at": str(run.resume_at)}, 0)
                run.save(ignore_permissions=True)
                frappe.db.commit()
                return run.name

            outcome, next_id, status = _execute_with_retry(node, context, run, wf)
            _append_step(run, node, status, outcome, outcome.pop("_ms", 0))

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

    return run.name


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


def _execute_with_retry(node, context, run, wf):
    """Run one node, honouring its retry policy. Returns (outcome, next_id, status)."""
    attempts = cint(node.max_retries) + 1
    delay = cint(node.retry_delay) or 30
    last_error = None

    for attempt in range(1, attempts + 1):
        started = time.time()
        try:
            outcome, next_id = _execute(node, context, run)
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

def _execute(node, context, run):
    """Run one node. Returns (outcome_dict, next_node_id)."""
    cfg = _cfg(node)
    doc = context.get("doc")
    payload = context.get("payload")
    kind = node.node_type

    if kind == "Trigger":
        return {"ok": True}, node.next_node

    if kind == "Condition":
        expr = cfg.get("expression") or "True"
        result = bool(_eval(expr, doc, payload))
        return ({"expression": expr, "result": result},
                node.next_node if result else node.next_node_alt)

    if kind == "Update Field":
        if not doc:
            return {"skipped": "no document in context"}, node.next_node
        field, value = cfg.get("field"), _render(cfg.get("value"), context)
        if field:
            frappe.db.set_value(doc.doctype, doc.name, field, value)
        return {"field": field, "value": value}, node.next_node

    if kind == "Create Document":
        target = cfg.get("doctype")
        values = {k: _render(v, context) for k, v in (cfg.get("values") or {}).items()}
        created = frappe.get_doc({"doctype": target, **values}).insert(ignore_permissions=True)
        return {"created": created.name, "doctype": target}, node.next_node

    if kind == "Send WhatsApp":
        return _send_whatsapp(cfg, context, doc, run, node), node.next_node

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
        frappe.sendmail(
            recipients=[recipient],
            subject=_render(cfg.get("subject"), context) or "(no subject)",
            message=_render(cfg.get("message"), context) or "",
            reference_doctype=doc.doctype if doc else None,
            reference_name=doc.name if doc else None,
        )
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
        # An approval is a genuine pause. Resuming is the approval's job.
        run.status = "Waiting"
        run.resume_node = node.next_node
        return {"approval": approval.name}, None

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
        msgs = get_conversation(doc.doctype, doc.name)
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

    if kind == "Webhook":
        import requests

        resp = requests.post(cfg.get("url"), json=cfg.get("body") or {}, timeout=20)
        return {"status_code": resp.status_code}, node.next_node

    return {"unhandled": kind}, node.next_node


def _send_whatsapp(cfg, context, doc, run, node):
    if "frappe_whatsapp" not in frappe.get_installed_apps():
        return {"skipped": "frappe_whatsapp not installed"}

    to = _render(cfg.get("to"), context) or (doc.get("mobile_no") if doc else None)
    if not to:
        return {"skipped": "no recipient"}

    # One send per node per run, however many times the worker retries.
    key = f"whatsapp:{run.name}:{node.node_id}"
    if already_done(key):
        return {"skipped": "already sent (idempotency)"}

    # THE GATE. Every AI-authored outbound passes here -- human handoff, quiet
    # hours, rate limits, do-not-contact and the global switch all refuse from
    # this one place. There is deliberately no second path to sending.
    author = cfg.get("author") or "ai"
    if author == "ai" and doc:
        allowed, mode, why = can_ai_send(doc.doctype, doc.name, channel="WhatsApp")
        if not allowed:
            log_action("whatsapp.send", status="Skipped", actor_type="AI_AGENT",
                       reference_doctype=doc.doctype, reference_name=doc.name,
                       workflow_run=run.name, node_id=node.node_id,
                       decision="SUPPRESSED", reason=why)
            return {"skipped": why}

        if mode == "Draft":
            approval = frappe.get_doc({
                "doctype": "Baton Approval",
                "kind": "Send Message",
                "status": "Pending",
                "draft_text": _render(cfg.get("message"), context),
                "reference_doctype": doc.doctype,
                "reference_name": doc.name,
                "payload": json.dumps({"to": to, "channel": "WhatsApp"}, default=str),
            }).insert(ignore_permissions=True)
            log_action("whatsapp.draft", actor_type="AI_AGENT",
                       reference_doctype=doc.doctype, reference_name=doc.name,
                       workflow_run=run.name, node_id=node.node_id,
                       decision="AWAIT_APPROVAL", reason="Draft mode is on for WhatsApp",
                       output={"approval": approval.name})
            return {"drafted": approval.name, "to": to}

    msg = frappe.get_doc({
        "doctype": "WhatsApp Message",
        "to": to,
        "message": _render(cfg.get("message"), context),
        "content_type": "text",
        "reference_doctype": doc.doctype if doc else None,
        "reference_name": doc.name if doc else None,
        # Baton's differentiator: who wrote this is a column, not a system.
        "baton_author": cfg.get("author") or "ai",
    }).insert(ignore_permissions=True)

    log_action("whatsapp.send", actor_type="AI_AGENT",
               reference_doctype=doc.doctype if doc else None,
               reference_name=doc.name if doc else None,
               workflow_run=run.name, node_id=node.node_id,
               idempotency_key=key, external_id=msg.name, output={"to": to})
    return {"whatsapp_message": msg.name, "to": to}


# ------------------------------------------------------------------ triggers

def handle_document_event(doc, method):
    """Fan a Frappe doc event out to any workflow listening for it."""
    if getattr(frappe.flags, "in_install", False) or getattr(frappe.flags, "in_migrate", False):
        return
    if not frappe.db.table_exists("Baton Workflow"):
        return

    names = frappe.get_all(
        "Baton Workflow",
        filters={"enabled": 1, "trigger_type": "Document Event",
                 "trigger_doctype": doc.doctype, "trigger_event": method},
        pluck="name",
    )
    for name in names:
        frappe.enqueue(
            "baton.workflow.engine.run_workflow",
            queue="short",
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
