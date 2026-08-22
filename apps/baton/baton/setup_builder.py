"""Schema for the no-code builder: multi-trigger workflows and parked runs.

Two structural changes here.

**Triggers become a child table.** A bot has to answer several things at once
("a lead was created" *and* "a deal stalled" *and* "every morning at 9"), which
four scalar fields on the parent cannot express. The old fields are migrated
across and then left in place read-only for one release, so a rollback does not
lose anything.

**Runs learn to wait for something other than a clock.** `waiting_for` splits a
timer wait from a wait on a customer reply or a human approval; `resume_node_alt`
is where the run goes when the wait times out instead of being satisfied. The
invariant the engine relies on is that *every* Waiting run has `resume_at` set --
it is the deadline for the alternate outcome, so nothing can park forever.
"""

import frappe

from baton.setup_phase1 import _add_fields, _doctype, _extend_select


def install():
    # ------------------------------------------------------------- triggers
    _doctype(
        "Baton Workflow Trigger",
        [
            {"fieldname": "enabled", "fieldtype": "Check", "label": "Enabled", "default": "1",
             "in_list_view": 1},
            {"fieldname": "trigger_type", "fieldtype": "Select", "label": "When", "reqd": 1,
             "options": "Document Event\nScheduled\nEvent\nWebhook\nManual",
             "default": "Document Event", "in_list_view": 1},
            {"fieldname": "trigger_doctype", "fieldtype": "Link", "label": "Record type",
             "options": "DocType", "in_list_view": 1,
             "depends_on": "eval:doc.trigger_type=='Document Event'"},
            {"fieldname": "trigger_event", "fieldtype": "Select", "label": "Event",
             "options": "after_insert\non_update\non_trash", "default": "after_insert",
             "depends_on": "eval:doc.trigger_type=='Document Event'"},
            {"fieldname": "field_changed", "fieldtype": "Data", "label": "Only when this field changes",
             "depends_on": "eval:doc.trigger_type=='Document Event' && doc.trigger_event=='on_update'",
             "description": "Blank fires on every save. Naming a field stops the on_update storm."},
            {"fieldname": "col_t", "fieldtype": "Column Break"},
            {"fieldname": "cron", "fieldtype": "Data", "label": "Cron",
             "depends_on": "eval:doc.trigger_type=='Scheduled'",
             "description": "Standard 5-field cron, e.g. 0 9 * * *"},
            {"fieldname": "event_name", "fieldtype": "Data", "label": "Event name",
             "depends_on": "eval:doc.trigger_type=='Event'",
             "description": "One of baton.events.EVENTS, e.g. lead.replied"},
            {"fieldname": "webhook_path", "fieldtype": "Data", "label": "Webhook path",
             "read_only": 1, "no_copy": 1, "unique": 1,
             "depends_on": "eval:doc.trigger_type=='Webhook'"},
            {"fieldname": "webhook_secret", "fieldtype": "Password", "label": "Webhook secret",
             "depends_on": "eval:doc.trigger_type=='Webhook'"},
            {"fieldname": "sec_tc", "fieldtype": "Section Break"},
            {"fieldname": "condition", "fieldtype": "Code", "label": "Only if",
             "description": "Optional Python expression over `doc`. Applied on top of the "
                            "workflow-level condition."},
        ],
        istable=1,
    )

    _add_fields("Baton Workflow", [
        {"fieldname": "kind", "fieldtype": "Select", "label": "Kind",
         "options": "Workflow\nBot", "default": "Workflow", "in_list_view": 1,
         "description": "A Bot reacts to a trigger and finishes. A Workflow may "
                        "also pause -- for a delay, a reply, or an approval."},
        {"fieldname": "sec_triggers", "fieldtype": "Section Break", "label": "When this happens"},
        {"fieldname": "triggers", "fieldtype": "Table", "label": "Triggers",
         "options": "Baton Workflow Trigger"},
        {"fieldname": "description", "fieldtype": "Small Text", "label": "Description"},
    ])

    # ------------------------------------------------------------ parked runs
    _add_fields("Baton Workflow Run", [
        {"fieldname": "sec_wait", "fieldtype": "Section Break", "label": "Waiting on"},
        {"fieldname": "waiting_for", "fieldtype": "Select", "label": "Waiting for",
         "options": "\nTimer\nReply\nApproval",
         "description": "Timer resumes on the clock. Reply and Approval resume on an "
                        "external event, with resume_at as their deadline."},
        {"fieldname": "waiting_channel", "fieldtype": "Select", "label": "On channel",
         "options": "\nAny\nWhatsApp\nEmail"},
        {"fieldname": "waiting_since", "fieldtype": "Datetime", "label": "Waiting since",
         "description": "A message older than this cannot resume the run."},
        {"fieldname": "col_wait", "fieldtype": "Column Break"},
        {"fieldname": "resume_node_alt", "fieldtype": "Data", "label": "Resume at node (timeout)",
         "description": "Taken when the wait times out rather than being satisfied."},
        {"fieldname": "run_reason", "fieldtype": "Data", "label": "Started by", "read_only": 1},
        {"fieldname": "sec_ctx", "fieldtype": "Section Break", "label": "Context"},
        {"fieldname": "context", "fieldtype": "Code", "options": "JSON", "label": "Context",
         "description": "Values carried across parks. Addressable as `vars` in conditions "
                        "and templates."},
    ])

    # -------------------------------------------------------------- approvals
    # Approvals could not resume the run that created them because nothing
    # recorded which run that was.
    _add_fields("Baton Approval", [
        {"fieldname": "workflow_run", "fieldtype": "Link", "label": "Workflow run",
         "options": "Baton Workflow Run", "read_only": 1,
         "description": "Resolving this approval resumes this run."},
    ])

    # ------------------------------------------------------------------ nodes
    _extend_select("Baton Workflow Node", "node_type", ["Await Reply"])

    # CRM-shaped actions. The palette used to offer machinery ("Update Record",
    # "HTTP Request") and leave the user to work out how that maps onto a lead;
    # these are the verbs the CRM itself uses.
    _extend_select("Baton Workflow Node", "node_type",
                   ["Assign To", "Add Comment", "Create Note", "Convert Lead"])
    _add_fields("Baton Workflow Node", [
        {"fieldname": "save_as", "fieldtype": "Data", "label": "Save result as",
         "description": "Writes this node's result into the run context under this key."},
    ])

    frappe.db.commit()
    print("Builder schema ready.")


def migrate_triggers():
    """Copy the old scalar trigger fields into the child table.

    Idempotent: a workflow that already has triggers is left alone, so this is
    safe to re-run and safe to run on a partially-migrated site.
    """
    moved = 0
    for name in frappe.get_all("Baton Workflow", pluck="name"):
        wf = frappe.get_doc("Baton Workflow", name)
        if wf.get("triggers"):
            continue
        if not wf.get("trigger_type"):
            continue

        wf.append("triggers", {
            "enabled": 1,
            "trigger_type": wf.trigger_type,
            "trigger_doctype": wf.get("trigger_doctype"),
            "trigger_event": wf.get("trigger_event"),
            "cron": wf.get("cron"),
            "event_name": wf.get("trigger_event_name"),
        })
        wf.save(ignore_permissions=True)
        moved += 1

    frappe.db.commit()
    print(f"  ~ migrated {moved} workflow(s) onto the triggers table")


def add_indexes():
    """Indexes the scheduler and the inbound resume path scan on every tick."""
    for fields in (["status", "resume_at"],
                   ["reference_doctype", "reference_name", "status"]):
        try:
            frappe.db.add_index("Baton Workflow Run", fields)
            print(f"  + index on {', '.join(fields)}")
        except Exception as e:
            print(f"  = index on {', '.join(fields)} ({e})")
    frappe.db.commit()


def install_all():
    install()
    migrate_triggers()
    add_indexes()
