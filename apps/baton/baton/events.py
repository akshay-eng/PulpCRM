"""Baton's event bus (spec §35).

A thin naming layer over Frappe's queues. Automation subscribes to event names
rather than to Frappe doc events directly, so a workflow can be triggered by
`lead.replied` without every producer knowing what a workflow is.

Deliberately thin: Frappe already provides the queue, the retry and the worker.
Re-implementing those would be the "another queue" mistake spec §43 warns about.
"""

import frappe

from baton.workflow.engine import RUN_QUEUE, RUN_TIMEOUT

# The catalogue from spec §35. Kept explicit so a typo in an event name fails
# loudly at emit time rather than silently never matching a subscriber.
EVENTS = {
    "lead.created", "lead.updated", "lead.replied", "lead.qualified",
    "lead.disqualified", "lead.followup_due", "lead.followup_failed",
    "deal.created", "deal.assigned", "deal.stage_changed", "deal.stalled",
    "task.created", "task.due", "task.overdue", "task.completed",
    "message.received", "message.sent",
    "human.intervention.detected",
    "workflow.started", "workflow.completed", "workflow.failed",
}


def emit(event, reference_doctype=None, reference_name=None, payload=None, now=False):
    """Publish an event. Matching workflows are enqueued, not run inline."""
    if event not in EVENTS:
        frappe.throw(f"Unknown Baton event '{event}'. Add it to baton.events.EVENTS.")

    if not frappe.db.table_exists("Baton Workflow"):
        return []

    # workflow.* is observability, not a hook: it still gets logged below, but
    # nothing may subscribe to it. A workflow triggering on its own completion
    # is a loop the cycle guard cannot see, because each turn is a separate run.
    subscribable = not event.startswith("workflow.")

    names = frappe.get_all(
        "Baton Workflow Trigger",
        filters={"parenttype": "Baton Workflow", "enabled": 1,
                 "trigger_type": "Event", "event_name": event},
        pluck="parent",
    ) if subscribable else []
    if names:
        names = frappe.get_all(
            "Baton Workflow",
            filters={"name": ["in", list(set(names))], "enabled": 1},
            pluck="name",
        )

    for name in names:
        frappe.enqueue(
            "baton.workflow.engine.run_workflow",
            queue=RUN_QUEUE,
            timeout=RUN_TIMEOUT,
            now=now,
            workflow_name=name,
            reference_doctype=reference_doctype,
            reference_name=reference_name,
            run_reason=event,
            event_payload=payload,
        )

    from baton.audit import log_action

    log_action(
        f"event.{event}",
        actor_type="SYSTEM",
        reference_doctype=reference_doctype,
        reference_name=reference_name,
        output={"subscribers": names},
        reason=f"{len(names)} workflow(s) subscribed",
    )
    return names
