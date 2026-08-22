"""Starting a workflow from an inbound HTTP call.

`Webhook` has been a trigger_type option since the beginning with nothing behind
it. This is that.

Mirrors the pattern api/webhook.py already established for WhatsApp: the request
is authenticated by HMAC over the raw body, and it **fails closed** -- a trigger
with no secret refuses everything rather than accepting anything. An open
endpoint that starts CRM automations is a considerably worse hole than an open
endpoint that logs a message.
"""

import hashlib
import hmac
import json

import frappe

from baton.audit import log_action
from baton.workflow.engine import RUN_QUEUE, RUN_TIMEOUT

SIGNATURE_HEADER = "X-Baton-Signature-256"


def verify_signature(raw_body, header_value, secret):
    """Constant-time compare of sha256=<hex> against the body."""
    if not (raw_body and header_value and secret):
        return False
    sent = header_value.strip()
    if sent.startswith("sha256="):
        sent = sent[len("sha256="):]
    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body if isinstance(raw_body, bytes) else raw_body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, sent)


def _reject(reason, path=None, status=403):
    log_action("webhook.trigger", status="Failed", actor_type="SYSTEM",
               decision="REJECTED", reason=reason, output={"path": path})
    frappe.local.response["http_status_code"] = status
    return {"ok": False, "error": reason}


@frappe.whitelist(allow_guest=True)
def receive(path=None):
    """Fire the workflow whose Webhook trigger owns `path`.

    Guest-accessible by necessity -- the caller is a third party. Everything
    that follows exists because of that.
    """
    if not path:
        return _reject("No webhook path given.", status=404)

    row = frappe.db.get_value(
        "Baton Workflow Trigger",
        {"webhook_path": path, "parenttype": "Baton Workflow"},
        ["name", "parent", "enabled", "condition"],
        as_dict=True,
    )
    if not row:
        # Deliberately the same shape as a signature failure: probing for valid
        # paths should not be any more informative than probing for secrets.
        return _reject("Unknown webhook.", path=path, status=404)

    if not row.enabled:
        return _reject("This trigger is switched off.", path=path)

    workflow = frappe.db.get_value("Baton Workflow", row.parent,
                                   ["name", "enabled"], as_dict=True)
    if not workflow or not workflow.enabled:
        return _reject("That workflow is not active.", path=path)

    secret = frappe.utils.password.get_decrypted_password(
        "Baton Workflow Trigger", row.name, "webhook_secret", raise_exception=False)
    if not secret:
        # Fail closed. A trigger with no secret is unconfigured, not public.
        return _reject("No webhook secret is configured for this trigger.", path=path)

    raw = frappe.request.get_data() if frappe.request else b""
    signature = (frappe.get_request_header(SIGNATURE_HEADER)
                 or frappe.get_request_header(SIGNATURE_HEADER.lower()))
    if not verify_signature(raw, signature, secret):
        return _reject("Signature does not match.", path=path)

    try:
        payload = json.loads(raw or b"{}")
    except (json.JSONDecodeError, TypeError):
        payload = {"raw": (raw or b"").decode("utf-8", "replace")[:2000]}

    # The caller may name a CRM record for the run to act on, but may not name
    # an arbitrary doctype -- that would let an authenticated third party point
    # a workflow at any table in the site.
    ref_dt = payload.get("reference_doctype")
    ref_dn = payload.get("reference_name")
    from baton.api.workflow import BUILDER_DOCTYPES

    if ref_dt not in BUILDER_DOCTYPES:
        ref_dt, ref_dn = None, None

    frappe.enqueue(
        "baton.workflow.engine.run_workflow",
        queue=RUN_QUEUE,
        timeout=RUN_TIMEOUT,
        enqueue_after_commit=True,
        workflow_name=workflow.name,
        reference_doctype=ref_dt,
        reference_name=ref_dn,
        run_reason="webhook",
        event_payload=payload,
    )
    log_action("webhook.trigger", actor_type="SYSTEM",
               reference_doctype=ref_dt, reference_name=ref_dn,
               output={"workflow": workflow.name, "path": path})
    return {"ok": True, "queued": workflow.name}
