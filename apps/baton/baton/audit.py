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
from contextlib import contextmanager
from contextvars import ContextVar

import frappe
from frappe.utils import add_to_date, now_datetime

# User-facing records whose mutations must be explainable from one place. Child
# rows are captured as part of their parent, so they deliberately do not appear
# here as separate, noisy entries.
AUDITED_DOCTYPES = (
    "CRM Lead",
    "CRM Deal",
    "Contact",
    "CRM Organization",
    "CRM Task",
    "FCRM Note",
    "CRM Call Log",
    "Baton Bot",
    "Baton Workflow",
)

_AUDIT_CONTEXT = ContextVar("pulp_audit_context", default=None)
_IGNORED_FIELDS = {
    "doctype", "name", "owner", "creation", "modified", "modified_by",
    "docstatus", "idx", "parent", "parenttype", "parentfield", "_user_tags",
    "_comments", "_assign", "_liked_by",
}
_IGNORED_FIELDTYPES = {
    "Section Break", "Column Break", "Tab Break", "HTML", "Button",
    "Password", "Attach", "Attach Image", "Signature",
}


@contextmanager
def audit_context(**values):
    """Attach a source and optional reason to every record write in a scope.

    ContextVar is important here: workflow and bot jobs overlap in the same
    worker process, so a module global could attribute one run's writes to
    another. Values are intentionally operational context, never model chain of
    thought.
    """
    current = dict(_AUDIT_CONTEXT.get() or {})
    current.update({key: value for key, value in values.items() if value is not None})
    token = _AUDIT_CONTEXT.set(current)
    try:
        yield
    finally:
        _AUDIT_CONTEXT.reset(token)


def _serializable(value, limit=1500):
    if hasattr(value, "as_dict"):
        value = value.as_dict(no_nulls=True)
    try:
        packed = json.dumps(value, default=str, sort_keys=True)
    except (TypeError, ValueError):
        packed = json.dumps(str(value))
    if len(packed) > limit:
        return packed[: limit - 1] + "…"
    try:
        return json.loads(packed)
    except json.JSONDecodeError:
        return packed


def _snapshot(doc):
    """Return the useful, non-secret state of a document for comparison."""
    values = {}
    for field in doc.meta.fields:
        if field.fieldname in _IGNORED_FIELDS or field.fieldtype in _IGNORED_FIELDTYPES:
            continue
        value = doc.get(field.fieldname)
        if value in (None, "", []):
            continue
        if field.fieldtype in ("Table", "Table MultiSelect"):
            rows = []
            for row in value:
                rows.append({
                    key: _serializable(item, 500)
                    for key, item in row.as_dict(no_nulls=True).items()
                    if key not in _IGNORED_FIELDS and not str(key).startswith("_")
                })
            value = rows
        values[field.fieldname] = _serializable(value)
    return values


def _field_changes(doc, before, after):
    fields = {field.fieldname: field for field in doc.meta.fields}
    changes = []
    for fieldname in sorted(set(before) | set(after)):
        old_value = before.get(fieldname)
        new_value = after.get(fieldname)
        if old_value == new_value:
            continue
        field = fields.get(fieldname)
        changes.append({
            "field": fieldname,
            "label": (field.label if field else None) or fieldname.replace("_", " ").title(),
            "before": old_value,
            "after": new_value,
        })
    return changes[:60]


def _bounded_changes(changes, limit=7000):
    """Keep the change list valid JSON within Baton Action Log's payload cap."""
    kept = []
    for index, change in enumerate(changes or []):
        compact = {
            "field": change.get("field"),
            "label": change.get("label"),
            "before": _serializable(change.get("before"), 1200),
            "after": _serializable(change.get("after"), 1200),
        }
        if len(json.dumps([*kept, compact], default=str)) > limit:
            kept.append({
                "field": "_more_changes",
                "label": "Additional changes",
                "before": None,
                "after": f"{len(changes) - index} more field(s) changed",
            })
            break
        kept.append(compact)
    return kept


def _record_title(doc):
    title_field = doc.meta.title_field
    return str(doc.get(title_field) or doc.name) if title_field else str(doc.name)


def _default_actor_type():
    request = getattr(frappe.local, "request", None)
    user = getattr(getattr(frappe, "session", None), "user", None)
    return "HUMAN" if request and user and user != "Guest" else "SYSTEM"


def _default_source():
    return "User interface" if getattr(frappe.local, "request", None) else "System"


def record_event(
    reference_doctype,
    reference_name,
    event,
    *,
    changes=None,
    reason=None,
    title=None,
    source=None,
    **extra,
):
    """Write one immutable record-history entry using the active context."""
    context = dict(_AUDIT_CONTEXT.get() or {})
    metadata = {
        "source": source or context.get("source") or _default_source(),
        "title": title or reference_name,
        "danger_mode": bool(context.get("danger_mode")),
    }
    metadata.update(extra)
    return log_action(
        f"record.{event}",
        actor_type=context.get("actor_type") or _default_actor_type(),
        actor_id=context.get("actor_id"),
        reference_doctype=reference_doctype,
        reference_name=reference_name,
        workflow=context.get("workflow"),
        workflow_run=context.get("workflow_run"),
        node_id=context.get("node_id"),
        bot=context.get("bot"),
        input={"changes": _bounded_changes(changes)},
        output=metadata,
        decision="DANGER_MODE" if context.get("danger_mode") else context.get("decision"),
        reason=reason if reason is not None else context.get("reason"),
    )


def record_document_event(doc, method, *args, **kwargs):
    """Frappe document hook for create, update, delete and rename events."""
    if doc.doctype not in AUDITED_DOCTYPES:
        return
    if getattr(frappe.flags, "in_install", False) or getattr(frappe.flags, "in_migrate", False):
        return
    if not frappe.db.table_exists("Baton Action Log"):
        return
    if method == "on_update" and getattr(doc.flags, "in_insert", False):
        return

    before_doc = doc.get_doc_before_save() if method == "on_update" else None
    before = _snapshot(before_doc) if before_doc else {}
    after = _snapshot(doc)
    event = "updated"
    if method == "after_insert":
        event = "created"
    elif method == "on_trash":
        event, before, after = "deleted", after, {}
    elif method == "after_rename":
        old, new = [*list(args), None, None][:2]
        return record_event(
            doc.doctype,
            new or doc.name,
            "renamed",
            changes=[{"field": "name", "label": "Name", "before": old, "after": new}],
            title=_record_title(doc),
        )

    changes = _field_changes(doc, before, after)
    if event == "updated" and not changes:
        return
    return record_event(
        doc.doctype,
        doc.name,
        event,
        changes=changes,
        title=_record_title(doc),
    )


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
    bot=None,
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
            "bot": bot,
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


# Retention. Per-node commits and per-turn agent logs mean a busy tenant writes
# thousands of rows a day, and this table is queried on every send to answer
# "have we already done this?" (already_done) and "how many did we send today?"
# (the rate limit). Letting it grow without bound degrades the send path itself.
SUCCESS_RETENTION_DAYS = 90
FAILURE_RETENTION_DAYS = 365


def purge_old_logs(limit=5000):
    """Trim Baton Action Log.

    Successes age out fast: after three months "we sent this" is history, and
    the idempotency keys guarding against double-sends are long dead. Failures
    and suppressions are kept four times longer because they are the rows
    someone actually goes looking for when asking why a message did not go out.
    """
    if not frappe.db.table_exists("Baton Action Log"):
        return

    deleted = 0
    for statuses, days in (
        (["Success"], SUCCESS_RETENTION_DAYS),
        (["Failed", "Skipped"], FAILURE_RETENTION_DAYS),
    ):
        cutoff = add_to_date(now_datetime(), days=-days)
        names = frappe.get_all(
            "Baton Action Log",
            filters={
                "status": ["in", statuses],
                "creation": ["<", cutoff],
                # Record history is the durable source of who changed what.
                # Operational run logs may expire; this trail may not.
                "action": ["not like", "record.%"],
            },
            pluck="name",
            limit_page_length=limit,
        )
        for name in names:
            frappe.delete_doc("Baton Action Log", name, force=True,
                              ignore_permissions=True, delete_permanently=True)
        deleted += len(names)

    if deleted:
        frappe.db.commit()
    return deleted
