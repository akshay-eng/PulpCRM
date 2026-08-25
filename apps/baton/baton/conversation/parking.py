"""Waking a parked run when the thing it was waiting for happens.

The scheduler handles the deadline half (a wait that timed out). This module
handles the satisfied half: a customer replied, or a human resolved an approval.

Both go through `claim_run` because they race each other -- a reply can land in
the same second the deadline fires -- and whoever claims first wins. The loser
does nothing at all.
"""

import frappe
from frappe.utils import get_datetime

from baton.audit import log_action
from baton.workflow.claim import claim_run
from baton.workflow.engine import RUN_QUEUE, RUN_TIMEOUT


def _waiting_run(reference_doctype, reference_name, waiting_for, channel=None):
    filters = {
        "status": "Waiting",
        "waiting_for": waiting_for,
        "reference_doctype": reference_doctype,
        "reference_name": reference_name,
        # A run parked waiting on a specific person (an assignee, not this
        # record's own contact) must never be woken by a reply from the
        # record's actual contact -- they both point at the same reference,
        # but the reply that arrived isn't from the person this run is
        # actually waiting on. See resume_waiting_assignee for that path.
        "waiting_from_number": ["is", "not set"],
    }
    if channel:
        filters["waiting_channel"] = ["in", [channel, "Any"]]

    rows = frappe.get_all(
        "Baton Workflow Run",
        filters=filters,
        fields=["name", "workflow", "bot", "waiting_since", "resume_node"],
        order_by="waiting_since desc",
        limit_page_length=1,
    )
    return rows[0] if rows else None


def resume_on_inbound(reference_doctype, reference_name, channel, message_name):
    """A contact replied. Continue whichever run was waiting to hear from them.

    Returns the run name if one was woken, else None.
    """
    run = _waiting_run(reference_doctype, reference_name, "Reply", channel)
    if not run:
        return None

    # A webhook redelivering an old message must not wake a run that parked
    # after it was sent -- the run would read a reply to a question it never
    # asked.
    from baton.conversation.thread import message_text_and_time

    _, sent_at = message_text_and_time(channel, message_name)
    if sent_at and run.waiting_since and get_datetime(sent_at) < get_datetime(run.waiting_since):
        return None

    if not claim_run(run.name):
        return None

    if run.bot:
        # A bot resumes by re-entering its loop with the reply as its next
        # observation, not by continuing at a node -- it has no graph.
        frappe.enqueue(
            "baton.bots.runtime.run_bot",
            queue=RUN_QUEUE,
            timeout=RUN_TIMEOUT,
            enqueue_after_commit=True,
            job_id=f"baton-run-{run.name}",
            deduplicate=True,
            bot_name=run.bot,
            resume_run=run.name,
            inbound_message=message_name,
            inbound_channel=channel,
            run_reason="reply",
        )
        log_action("run.resumed", reference_doctype=reference_doctype,
                   reference_name=reference_name, workflow_run=run.name,
                   bot=run.bot, reason=f"Inbound {channel} message",
                   output={"message": message_name})
        return run.name

    frappe.enqueue(
        "baton.workflow.engine.run_workflow",
        queue=RUN_QUEUE,
        timeout=RUN_TIMEOUT,
        # The worker reads the message back out of the DB, so it must not start
        # before this transaction lands.
        enqueue_after_commit=True,
        job_id=f"baton-run-{run.name}",
        deduplicate=True,
        workflow_name=run.workflow,
        resume_run=run.name,
        resume_at_node=run.resume_node,
        resume_phase="reply",
        inbound_message=message_name,
        run_reason="reply",
    )
    log_action("run.resumed", reference_doctype=reference_doctype,
               reference_name=reference_name, workflow_run=run.name,
               reason=f"Inbound {channel} message", output={"message": message_name})
    return run.name


def _waiting_on_number(number, channel):
    """The most recently parked run waiting on a reply from this specific
    phone number, or None.

    If the same person is the assignee on two records with runs parked
    waiting on them at once, one inbound message is genuinely ambiguous
    between them. Most-recently-parked wins -- usually right (someone just
    asked something is answering *that*, not a stale ask from days ago) and
    bounded: the other run isn't cancelled or fed the wrong reply, it just
    keeps waiting and times out on its own schedule.
    """
    if not number:
        return None
    rows = frappe.get_all(
        "Baton Workflow Run",
        filters={"status": "Waiting", "waiting_for": "Reply",
                 "waiting_channel": ["in", [channel, "Any"]],
                 "waiting_from_number": ["is", "set"]},
        fields=["name", "bot", "waiting_from_number", "waiting_since"],
        order_by="waiting_since desc",
    )
    from baton.bots.approval import same_number

    for row in rows:
        if same_number(row.waiting_from_number, number):
            return row
    return None


def resume_waiting_assignee(sender, channel, message_name):
    """An assignee replied. Continue whichever run was waiting to hear from
    them specifically -- matched by phone number, not by CRM reference,
    since the assignee's own number essentially never resolves back to the
    lead/deal record the way a contact's own number does.

    Returns the run name if one was woken, else None.
    """
    run = _waiting_on_number(sender, channel)
    if not run:
        return None

    from baton.conversation.thread import message_text_and_time

    _, sent_at = message_text_and_time(channel, message_name)
    if sent_at and run.waiting_since and get_datetime(sent_at) < get_datetime(run.waiting_since):
        return None

    if not claim_run(run.name):
        return None

    # Bot-only by construction: a plain workflow run has no ask_assignee
    # equivalent today.
    frappe.enqueue(
        "baton.bots.runtime.run_bot",
        queue=RUN_QUEUE,
        timeout=RUN_TIMEOUT,
        enqueue_after_commit=True,
        job_id=f"baton-run-{run.name}",
        deduplicate=True,
        bot_name=run.bot,
        resume_run=run.name,
        inbound_message=message_name,
        inbound_channel=channel,
        inbound_from_assignee=True,
        run_reason="reply",
    )
    log_action("run.resumed", workflow_run=run.name, bot=run.bot,
               reason=f"Inbound {channel} message from assignee",
               output={"message": message_name})
    return run.name


@frappe.whitelist()
def resolve_approval(approval, decision, note=None):
    """Approve or reject from the CRM, and continue whatever was waiting.

    The decision itself lives in baton.bots.approval.resolve, because the same
    answer can arrive from an emailed link or a WhatsApp reply and must mean the
    same thing however it got here. This endpoint only adds the permission check
    that a logged-in caller needs.
    """
    from baton.bots.approval import resolve

    frappe.only_for(["System Manager", "Sales Manager"])

    if decision not in ("Approved", "Rejected"):
        frappe.throw(frappe._("Decision must be Approved or Rejected"))

    doc = frappe.get_doc("Baton Approval", approval)
    if doc.status != "Pending":
        return {"ok": False,
                "message": frappe._("This approval is already {0}.").format(doc.status)}

    return resolve(doc, decision, by=frappe.session.user, note=note)


def resume_workflow_after_approval(run, decision):
    """Continue a *workflow* run past its approval node.

    Approval continues down the node's normal branch; rejection takes the
    alternate one, which is the same route a timeout takes. A bot has no graph,
    so this path does not apply to it.
    """
    target = run.resume_node if decision == "Approved" else run.resume_node_alt
    if not claim_run(run.name):
        return {"ok": True, "resumed": None}

    if not target:
        frappe.db.set_value("Baton Workflow Run", run.name, {
            "status": "Completed" if decision == "Approved" else "Cancelled",
            "cancelled_reason": None if decision == "Approved" else "Approval rejected",
        })
        frappe.db.commit()
        return {"ok": True, "resumed": run.name}

    frappe.enqueue(
        "baton.workflow.engine.run_workflow",
        queue=RUN_QUEUE,
        timeout=RUN_TIMEOUT,
        enqueue_after_commit=True,
        job_id=f"baton-run-{run.name}",
        deduplicate=True,
        workflow_name=run.workflow,
        resume_run=run.name,
        resume_at_node=target,
        run_reason=f"approval:{decision.lower()}",
    )
    return {"ok": True, "resumed": run.name}

    frappe.enqueue(
        "baton.workflow.engine.run_workflow",
        queue=RUN_QUEUE,
        timeout=RUN_TIMEOUT,
        enqueue_after_commit=True,
        job_id=f"baton-run-{run.name}",
        deduplicate=True,
        workflow_name=run.workflow,
        resume_run=run.name,
        resume_at_node=target,
        run_reason=f"approval:{decision.lower()}",
    )
    return {"ok": True, "resumed": run.name}
