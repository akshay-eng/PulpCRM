"""Turns a Followup Policy into a visible workflow graph.

The ladder could have been a hardcoded loop. Materialising it as a
`Baton Workflow` instead means the owner can open it in the canvas, see exactly
what will happen and when, and change it without a developer -- which is the
whole point of spec §93's no-code requirement.

Regenerating is idempotent: the workflow is rebuilt from the policy, so editing
the policy and rebuilding never accumulates duplicate nodes.
"""

import json

import frappe

from baton.workflow.build import node as build_node
from frappe.utils import cint

WORKFLOW_PREFIX = "Follow-up — "


# Kept as a thin alias so this module reads as it did, while there is only one
# node builder in the app. See baton.workflow.build.
def _n(node_id, node_type, label, config=None, next_node=None, next_node_alt=None,
       x=420, y=0, **kw):
    return build_node(node_id, node_type, label, config=config, next_node=next_node,
                      next_node_alt=next_node_alt, x=x, y=y, **kw)


def build_workflow_from_policy(policy_name=None, trigger_doctype="CRM Lead"):
    """(Re)generate the workflow that implements a follow-up policy."""
    policy = frappe.get_doc(
        "Baton Followup Policy",
        policy_name or frappe.db.get_value(
            "Baton Followup Policy", {"is_default": 1, "enabled": 1}, "name"),
    )

    name = f"{WORKFLOW_PREFIX}{policy.policy_name}"
    steps = sorted(policy.steps, key=lambda s: cint(s.step))[: cint(policy.max_attempts) or 4]

    nodes = [_n("trigger", "Trigger", "New lead", next_node="s1_send" if steps else "escalate",
                y=40)]
    row = 1

    for i, step in enumerate(steps, start=1):
        is_last = i == len(steps)
        send_id, wait_id, check_id = f"s{i}_send", f"s{i}_wait", f"s{i}_check"
        nxt_send = f"s{i+1}_send" if not is_last else "escalate"

        channel_node = "Send WhatsApp" if step.channel == "WhatsApp" else "Send Email"
        cfg = {
            # The prompt is an instruction to the agent, not a literal message.
            "prompt": step.prompt,
            "author": "ai",
        }
        if step.channel == "WhatsApp":
            cfg["to"] = "{{ doc.mobile_no }}"
            cfg["message"] = step.prompt
        else:
            cfg["to"] = "{{ doc.email }}"
            cfg["subject"] = "Following up on your enquiry"
            cfg["message"] = step.prompt

        nodes.append(_n(send_id, channel_node, f"{i}. {step.channel}", cfg,
                        next_node=wait_id, y=row * 130 + 40))
        row += 1
        nodes.append(_n(wait_id, "Wait",
                        f"Wait {step.wait_amount} {step.wait_unit}",
                        {"amount": cint(step.wait_amount), "unit": step.wait_unit},
                        next_node=check_id, y=row * 130 + 40))
        row += 1
        # Replied -> stop the ladder. Not replied -> next rung.
        nodes.append(_n(check_id, "Check Reply", "Did they reply?",
                        next_node="replied", next_node_alt=nxt_send,
                        y=row * 130 + 40))
        row += 1

    nodes.append(_n("replied", "Update Field", "Mark as engaged",
                    {"field": "communication_status", "value": "Replied"},
                    x=760, y=200))

    escalate_next = "notify" if policy.notify_owner else None
    if policy.create_task:
        nodes.append(_n("escalate", "Create Task", "Human call task",
                        {"subject": policy.task_subject,
                         "description": "Automated follow-ups exhausted with no reply.",
                         "priority": "High"},
                        next_node=escalate_next, y=row * 130 + 40))
    if policy.notify_owner:
        nodes.append(_n("notify", "Create Document", "Notify owner",
                        {"doctype": "CRM Notification",
                         "values": {
                             "to_user": "{{ doc.lead_owner }}",
                             "type": "Mention",
                             "notification_text": "Lead {{ doc.lead_name }} did not respond to follow-ups",
                             "reference_doctype": "CRM Lead",
                             "reference_name": "{{ doc.name }}",
                         }},
                        y=(row + 1) * 130 + 40))

    if frappe.db.exists("Baton Workflow", name):
        wf = frappe.get_doc("Baton Workflow", name)
        wf.set("nodes", [])
    else:
        wf = frappe.new_doc("Baton Workflow")
        wf.workflow_name = name

    # Triggers live on a child table now, so a workflow can answer several
    # things at once. Rebuilt rather than appended, since this whole function
    # regenerates the workflow from the policy.
    wf.trigger_type = "Document Event"
    wf.trigger_doctype = trigger_doctype
    wf.trigger_event = "after_insert"
    wf.set("triggers", [])
    wf.append("triggers", {
        "enabled": 1,
        "trigger_type": "Document Event",
        "trigger_doctype": trigger_doctype,
        "trigger_event": "after_insert",
    })
    # Generated workflows start switched off: nobody should discover that leads
    # were being messaged because a setup script ran.
    wf.enabled = 0
    for node in nodes:
        wf.append("nodes", node)
    wf.save(ignore_permissions=True)
    frappe.db.commit()
    return wf.name, len(nodes)


@frappe.whitelist()
def rebuild_default():
    frappe.only_for(["System Manager", "Sales Manager"])
    name, count = build_workflow_from_policy()
    return {"workflow": name, "nodes": count}
