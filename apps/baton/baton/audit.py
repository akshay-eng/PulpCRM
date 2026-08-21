"""Action logging and idempotency.

Two guarantees this module exists to provide:

  1. Every externally-visible action leaves exactly one `Baton Action Log` row,
     so spec §74's "why didn't the AI send the message?" is answerable from CRM
     records alone.
  2. An action carrying an idempotency key runs at most once, however many times
     a worker retries it (spec §49).
"""

import functools
import json
import time

import frappe


def _j(value, limit=8000):
    if value is None:
        return None
    try:
        return json.dumps(value, default=str)[:limit]
    except (TypeError, ValueError):
        return str(value)[:limit]


def log_action(
    action,
    status="Success",
    actor_type="SYSTEM",
    actor_id=None,
    reference_doctype=None,
    reference_name=None,
    workflow=None,
    workflow_run=None,
    node_id=None,
    ai_model=None,
    provider=None,
    external_id=None,
    idempotency_key=None,
    input=None,
    output=None,
    error=None,
    latency_ms=None,
    decision=None,
    confidence=None,
    reason=None,
):
    """Write one audit row. Never raises -- logging must not break the caller."""
    try:
        doc = frappe.get_doc({
            "doctype": "Baton Action Log",
            "action": action,
            "status": status,
            "actor_type": actor_type,
            "actor_id": actor_id or frappe.session.user,
            "reference_doctype": reference_doctype,
            "reference_name": reference_name,
            "workflow": workflow,
            "workflow_run": workflow_run,
            "node_id": node_id,
            "ai_model": ai_model,
            "provider": provider,
            "external_id": external_id,
            "idempotency_key": idempotency_key,
            "input": _j(input),
            "output": _j(output),
            "error": (error or "")[:2000] or None,
            "latency_ms": latency_ms,
            "decision": decision,
            "confidence": confidence,
            "reason": (reason or "")[:2000] or None,
        })
        doc.insert(ignore_permissions=True)
        return doc.name
    except Exception:
        frappe.log_error(title="Baton: failed to write action log")
        return None


def already_done(idempotency_key):
    """True when a successful action with this key has already been recorded."""
    if not idempotency_key:
        return False
    return bool(
        frappe.db.exists(
            "Baton Action Log", {"idempotency_key": idempotency_key, "status": "Success"}
        )
    )


def idempotent(key, action, **log_kw):
    """Decorator-style guard for a side-effecting call.

    Usage:
        with_guard = idempotent(key, "whatsapp.send", reference_name=lead)
        result = with_guard(lambda: send_the_message())

    Returns the callable's result, or None when the action was already done.
    """

    def runner(fn):
        if already_done(key):
            log_action(action, status="Skipped", idempotency_key=None,
                       reason=f"idempotency key {key} already succeeded", **log_kw)
            return None

        started = time.time()
        try:
            result = fn()
        except Exception as e:
            log_action(action, status="Failed", error=str(e),
                       latency_ms=int((time.time() - started) * 1000), **log_kw)
            raise
        log_action(action, status="Success", idempotency_key=key, output=result,
                   latency_ms=int((time.time() - started) * 1000), **log_kw)
        return result

    return runner


def timed(action, **log_kw):
    """Decorator that logs duration and outcome of a function call."""

    def wrap(fn):
        @functools.wraps(fn)
        def inner(*a, **kw):
            started = time.time()
            try:
                out = fn(*a, **kw)
            except Exception as e:
                log_action(action, status="Failed", error=str(e),
                           latency_ms=int((time.time() - started) * 1000), **log_kw)
                raise
            log_action(action, status="Success",
                       latency_ms=int((time.time() - started) * 1000), **log_kw)
            return out

        return inner

    return wrap
