"""Time-driven half of the workflow engine.

Two jobs, both run once a minute:
  * `resume_due_runs` wakes runs whose `resume_at` has passed (spec §107)
  * `tick` starts workflows whose cron expression is due
"""

import frappe
from croniter import croniter
from frappe.utils import now_datetime


def resume_due_runs(limit=100):
    """Continue any waiting run whose resume time has arrived."""
    if not frappe.db.table_exists("Baton Workflow Run"):
        return

    due = frappe.get_all(
        "Baton Workflow Run",
        filters={
            "status": "Waiting",
            "resume_at": ["<=", now_datetime()],
            "resume_node": ["is", "set"],
        },
        fields=["name", "workflow"],
        limit_page_length=limit,
    )

    for run in due:
        # Claim the run before enqueueing, so two scheduler ticks overlapping
        # cannot resume the same run twice.
        updated = frappe.db.sql(
            """UPDATE `tabBaton Workflow Run`
               SET status = 'Running'
               WHERE name = %s AND status = 'Waiting'""",
            run.name,
        )
        frappe.db.commit()
        if not updated:
            continue

        frappe.enqueue(
            "baton.workflow.engine.run_workflow",
            queue="short",
            workflow_name=run.workflow,
            resume_run=run.name,
            run_reason="resume",
        )


def tick():
    """Start scheduled workflows whose cron expression matches this minute."""
    if not frappe.db.table_exists("Baton Workflow"):
        return

    now = now_datetime()
    workflows = frappe.get_all(
        "Baton Workflow",
        filters={"enabled": 1, "trigger_type": "Scheduled"},
        fields=["name", "cron"],
    )

    for wf in workflows:
        if not wf.cron:
            continue
        try:
            # Due if the previous fire time for this expression falls inside the
            # minute that just elapsed.
            prev = croniter(wf.cron, now).get_prev(type(now))
            if (now - prev).total_seconds() < 60:
                frappe.enqueue(
                    "baton.workflow.engine.run_workflow",
                    queue="short",
                    workflow_name=wf.name,
                    run_reason="scheduled",
                )
        except Exception:
            frappe.log_error(title=f"Baton cron parse failed for {wf.name}")
