"""Time-driven half of the workflow engine.

Three jobs, all run once a minute:
  * `resume_due_runs` wakes runs whose `resume_at` has passed (spec §107)
  * `tick` starts workflows whose cron expression is due
  * `sweep_stale_runs` recovers runs whose worker died mid-flight
"""

import frappe
from croniter import croniter
from frappe.utils import add_to_date, now_datetime

from baton.workflow.claim import claim_run
from baton.workflow.engine import RUN_QUEUE, RUN_TIMEOUT

# A run that has not written a heartbeat in this long has lost its worker.
# Generously longer than the 1500s job timeout, so a slow-but-alive run is
# never stolen from underneath itself.
STALE_AFTER_MINUTES = 30


def resume_due_runs(limit=100):
    """Continue any waiting run whose resume time has arrived."""
    if not frappe.db.table_exists("Baton Workflow Run"):
        return

    # No `resume_node is set` filter any more: a wait that timed out with no
    # alternate branch still has to be closed out rather than left Waiting.
    due = frappe.get_all(
        "Baton Workflow Run",
        filters={"status": "Waiting", "resume_at": ["<=", now_datetime()]},
        fields=["name", "workflow", "bot", "waiting_for", "resume_node",
                "resume_node_alt"],
        limit_page_length=limit,
    )

    for run in due:
        # A Timer wait reaching its time is the wait *succeeding*, so it goes to
        # resume_node. Every other kind of wait reaching its deadline is the
        # thing it waited for never happening, so it takes the alternate branch.
        target = run.resume_node if (run.waiting_for or "Timer") == "Timer" else run.resume_node_alt

        # Claim before enqueueing, so two overlapping ticks cannot resume the
        # same run twice. claim_run reads its token back because an UPDATE
        # cannot report rows affected -- see baton.workflow.claim.
        if not claim_run(run.name):
            continue

        reason = "resume" if (run.waiting_for or "Timer") == "Timer" else "timeout"

        # A bot has no graph, so there is no node to continue at: it re-enters
        # its own loop knowing the wait ended. Routing on `run.bot` here is what
        # lets bots reuse every durable-wait guarantee workflows already have.
        if run.bot:
            frappe.enqueue(
                "baton.bots.runtime.run_bot",
                queue=RUN_QUEUE,
                timeout=RUN_TIMEOUT,
                job_id=f"baton-run-{run.name}",
                deduplicate=True,
                bot_name=run.bot,
                resume_run=run.name,
                run_reason=reason,
            )
            continue

        if not target:
            frappe.db.set_value("Baton Workflow Run", run.name, {
                "status": "Expired",
                "error": f"{run.waiting_for or 'Timer'} deadline passed with no branch to take.",
            })
            frappe.db.commit()
            continue

        # queue="long": one AI Agent node is llm.DEFAULT_TIMEOUT (90s) with up
        # to 3 chat_json retries, so a graph with two of them can legitimately
        # outlive the 300s "short" timeout and get killed mid-run.
        # job_id + deduplicate closes the last double-enqueue window.
        frappe.enqueue(
            "baton.workflow.engine.run_workflow",
            queue=RUN_QUEUE,
            timeout=RUN_TIMEOUT,
            job_id=f"baton-run-{run.name}",
            deduplicate=True,
            workflow_name=run.workflow,
            resume_run=run.name,
            resume_at_node=target,
            run_reason=reason,
        )


def tick():
    """Start anything whose cron expression matches this minute.

    Bots as well as workflows. The trigger table is shared, but this only ever
    queried `parenttype = "Baton Workflow"` -- so a bot could be given a
    schedule in the builder, saved, switched on, and would simply never run.
    """
    if not frappe.db.table_exists("Baton Workflow Trigger"):
        return

    now = now_datetime()
    _fire_due("Baton Workflow", "baton.workflow.engine.run_workflow", "workflow_name", now)
    if frappe.db.table_exists("Baton Bot"):
        _fire_due("Baton Bot", "baton.bots.runtime.run_bot", "bot_name", now)


def _is_due(cron, now):
    """Did this expression fire inside the minute that just elapsed?"""
    prev = croniter(cron, now).get_prev(type(now))
    return (now - prev).total_seconds() < 60


def _fire_due(parenttype, method, name_kwarg, now):
    if not frappe.db.table_exists(parenttype):
        return

    rows = frappe.get_all(
        "Baton Workflow Trigger",
        filters={"parenttype": parenttype, "enabled": 1, "trigger_type": "Scheduled"},
        fields=["parent as name", "cron"],
    )
    if not rows:
        return

    live = set(frappe.get_all(
        parenttype,
        filters={"name": ["in", list({r.name for r in rows})], "enabled": 1},
        pluck="name",
    ))

    for row in rows:
        if row.name not in live or not row.cron:
            continue
        try:
            if not _is_due(row.cron, now):
                continue
        except Exception:
            frappe.log_error(title=f"Baton cron parse failed for {row.name}")
            continue

        frappe.enqueue(
            method,
            queue=RUN_QUEUE,
            timeout=RUN_TIMEOUT,
            # One run per schedule per minute, even if two workers tick at once.
            job_id=f"baton-cron-{parenttype}-{row.name}-{now:%Y%m%d%H%M}",
            deduplicate=True,
            run_reason="scheduled",
            **{name_kwarg: row.name},
        )


def sweep_stale_runs(limit=50):
    """Recover runs whose worker died mid-flight.

    A run goes Waiting -> Running the moment it is claimed, so a worker that is
    SIGKILLed (job timeout, deploy, OOM) leaves the row Running forever with
    nothing scheduled to touch it again. Without this sweep those runs are
    invisible zombies: the lead never gets its follow-up and nothing says why.

    A run with a resume_node can simply be re-claimed and re-enqueued -- nodes
    are idempotent by key, so re-running the parked node is safe. One without a
    resume_node died mid-node with no recorded place to continue from, so it is
    failed honestly rather than restarted from the top, which would re-send
    anything the first attempt already sent under a different idempotency turn.
    """
    if not frappe.db.table_exists("Baton Workflow Run"):
        return

    cutoff = add_to_date(now_datetime(), minutes=-STALE_AFTER_MINUTES)
    stale = frappe.get_all(
        "Baton Workflow Run",
        filters={"status": "Running", "heartbeat_at": ["<", cutoff]},
        fields=["name", "workflow", "bot", "resume_node"],
        limit_page_length=limit,
    )

    for run in stale:
        if not run.resume_node:
            frappe.db.set_value("Baton Workflow Run", run.name, {
                "status": "Failed",
                "error": (
                    f"Worker stopped responding: no heartbeat for "
                    f"{STALE_AFTER_MINUTES} minutes and no node to resume from."
                ),
            })
            frappe.db.commit()
            continue

        if not claim_run(run.name, expect="Running"):
            continue

        if run.bot:
            frappe.enqueue(
                "baton.bots.runtime.run_bot",
                queue=RUN_QUEUE,
                timeout=RUN_TIMEOUT,
                job_id=f"baton-run-{run.name}",
                deduplicate=True,
                bot_name=run.bot,
                resume_run=run.name,
                run_reason="recovered",
            )
            continue

        frappe.enqueue(
            "baton.workflow.engine.run_workflow",
            queue=RUN_QUEUE,
            timeout=RUN_TIMEOUT,
            job_id=f"baton-run-{run.name}",
            deduplicate=True,
            workflow_name=run.workflow,
            resume_run=run.name,
            run_reason="recovered",
        )
