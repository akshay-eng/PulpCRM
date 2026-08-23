"""Phase 1 foundation DocTypes.

    bench --site crm.localhost execute baton.setup_phase1.install
"""

import frappe

MODULE = "Baton"


def _perms(roles=("System Manager", "Sales Manager")):
    return [
        {"role": r, "read": 1, "write": 1, "create": 1,
         "delete": 1 if r == "System Manager" else 0, "report": 1, "share": 1}
        for r in roles
    ]


def _doctype(name, fields, **kwargs):
    if frappe.db.exists("DocType", name):
        print(f"  = {name} (exists)")
        return
    frappe.get_doc({
        "doctype": "DocType", "name": name, "module": MODULE, "custom": 0,
        "fields": fields,
        "permissions": [] if kwargs.get("istable") else _perms(),
        **kwargs,
    }).insert(ignore_permissions=True)
    print(f"  + {name}")


def install():
    # ------------------------------------------------------- AI model config
    # Spec §11: provider, model and credentials are configuration, and each
    # purpose may use a different model (cheap one to summarise, strong one to
    # qualify).
    _doctype(
        "Baton AI Model",
        [
            {"fieldname": "model_name", "fieldtype": "Data", "label": "Name", "reqd": 1,
             "unique": 1, "in_list_view": 1},
            {"fieldname": "enabled", "fieldtype": "Check", "label": "Enabled", "default": "1",
             "in_list_view": 1},
            {"fieldname": "is_default", "fieldtype": "Check", "label": "Default model",
             "description": "Used when no model is configured for a purpose."},
            {"fieldname": "col_m", "fieldtype": "Column Break"},
            {"fieldname": "purpose", "fieldtype": "Select", "label": "Purpose", "in_list_view": 1,
             "options": "General\nQualification\nConversation\nSummarisation\nWorkflow",
             "default": "General"},
            {"fieldname": "provider", "fieldtype": "Select", "label": "Provider", "reqd": 1,
             "in_list_view": 1,
             "options": "OpenAI Compatible\nAnthropic\nGoogle Gemini\nOllama\nAzure OpenAI",
             "default": "OpenAI Compatible"},
            {"fieldname": "sec_conn", "fieldtype": "Section Break", "label": "Connection"},
            {"fieldname": "model", "fieldtype": "Data", "label": "Model", "reqd": 1,
             "description": "e.g. llama-3.3-70b-versatile, claude-sonnet-4-5, gemini-2.0-flash, llama3.2"},
            {"fieldname": "base_url", "fieldtype": "Data", "label": "Base URL",
             "description": "Blank uses the provider default. Ollama defaults to http://localhost:11434"},
            {"fieldname": "col_c", "fieldtype": "Column Break"},
            {"fieldname": "api_key", "fieldtype": "Password", "label": "API Key",
             "description": "Not required for Ollama."},
            {"fieldname": "api_version", "fieldtype": "Data", "label": "API Version",
             "depends_on": "eval:doc.provider=='Azure OpenAI'"},
            {"fieldname": "sec_tune", "fieldtype": "Section Break", "label": "Tuning"},
            {"fieldname": "temperature", "fieldtype": "Float", "label": "Temperature", "default": "0"},
            {"fieldname": "max_tokens", "fieldtype": "Int", "label": "Max tokens", "default": "2048"},
            {"fieldname": "col_t", "fieldtype": "Column Break"},
            {"fieldname": "timeout", "fieldtype": "Int", "label": "Timeout (s)", "default": "90"},
            {"fieldname": "max_retries", "fieldtype": "Int", "label": "Max retries", "default": "2"},
            {"fieldname": "sec_p", "fieldtype": "Section Break", "label": "Prompt"},
            {"fieldname": "system_prompt", "fieldtype": "Small Text", "label": "System prompt",
             "description": "Prepended to every call using this model."},
            {"fieldname": "prompt_version", "fieldtype": "Int", "label": "Prompt version",
             "default": "1", "read_only": 1,
             "description": "Bumped whenever the system prompt changes, so logged actions stay traceable (spec §86)."},
        ],
        title_field="model_name",
        autoname="field:model_name",
    )

    # ------------------------------------------------------------ action log
    # Spec §45-47: every external action attributable to an actor, a workflow
    # and a model. This is what makes §74's "why didn't it send?" answerable.
    _doctype(
        "Baton Action Log",
        [
            {"fieldname": "action", "fieldtype": "Data", "label": "Action", "reqd": 1,
             "in_list_view": 1, "in_standard_filter": 1},
            {"fieldname": "actor_type", "fieldtype": "Select", "label": "Actor",
             "options": "HUMAN\nAI_AGENT\nSYSTEM\nCONNECTOR\nMCP", "default": "SYSTEM",
             "in_list_view": 1, "in_standard_filter": 1},
            {"fieldname": "actor_id", "fieldtype": "Data", "label": "Actor ID"},
            {"fieldname": "col_a", "fieldtype": "Column Break"},
            {"fieldname": "status", "fieldtype": "Select", "label": "Status",
             "options": "Success\nFailed\nSkipped", "default": "Success",
             "in_list_view": 1, "in_standard_filter": 1},
            {"fieldname": "latency_ms", "fieldtype": "Int", "label": "Latency (ms)"},
            {"fieldname": "idempotency_key", "fieldtype": "Data", "label": "Idempotency key",
             "unique": 1,
             "description": "Set for side-effecting actions so a retry cannot double-send (spec §49)."},
            {"fieldname": "sec_ctx", "fieldtype": "Section Break", "label": "Context"},
            {"fieldname": "reference_doctype", "fieldtype": "Link", "label": "Reference Type",
             "options": "DocType"},
            {"fieldname": "reference_name", "fieldtype": "Dynamic Link", "label": "Reference",
             "options": "reference_doctype", "in_list_view": 1},
            {"fieldname": "col_ctx", "fieldtype": "Column Break"},
            {"fieldname": "workflow", "fieldtype": "Link", "label": "Workflow",
             "options": "Baton Workflow"},
            {"fieldname": "workflow_run", "fieldtype": "Link", "label": "Run",
             "options": "Baton Workflow Run"},
            {"fieldname": "node_id", "fieldtype": "Data", "label": "Node"},
            {"fieldname": "sec_model", "fieldtype": "Section Break", "label": "Model"},
            {"fieldname": "ai_model", "fieldtype": "Link", "label": "AI Model",
             "options": "Baton AI Model"},
            {"fieldname": "provider", "fieldtype": "Data", "label": "Provider"},
            {"fieldname": "col_model", "fieldtype": "Column Break"},
            {"fieldname": "external_id", "fieldtype": "Data", "label": "External message ID"},
            {"fieldname": "sec_io", "fieldtype": "Section Break", "label": "Payload"},
            {"fieldname": "input", "fieldtype": "Code", "label": "Input", "options": "JSON"},
            {"fieldname": "output", "fieldtype": "Code", "label": "Output", "options": "JSON"},
            {"fieldname": "error", "fieldtype": "Small Text", "label": "Error"},
            {"fieldname": "sec_dec", "fieldtype": "Section Break", "label": "Decision"},
            {"fieldname": "decision", "fieldtype": "Data", "label": "Decision"},
            {"fieldname": "confidence", "fieldtype": "Float", "label": "Confidence"},
            {"fieldname": "reason", "fieldtype": "Small Text", "label": "Reason",
             "description": "Concise operational reasoning only -- never hidden chain-of-thought (spec §47)."},
        ],
        autoname="hash",
        sort_field="creation",
        sort_order="DESC",
        permissions=[
            {"role": role, "read": 1, "report": 1, "export": 1, "print": 1, "email": 1}
            for role in ("System Manager", "Sales Manager")
        ],
    )

    frappe.db.commit()
    print("Phase 1 doctypes ready.")


def migrate_settings_to_model():
    """Carry the single-provider config on Baton Settings into a Baton AI Model.

    Baton Settings held one OpenAI-compatible provider. Rather than stranding
    that config, promote it to a default model so nothing breaks.
    """
    if frappe.db.exists("Baton AI Model", {"is_default": 1}):
        print("  = default model already exists")
        return

    s = frappe.get_single("Baton Settings")
    base = (s.get("ai_base_url") or "").strip()
    model = (s.get("ai_model") or "").strip()
    if not model:
        print("  ! Baton Settings has no model configured; nothing to migrate")
        return

    doc = frappe.get_doc({
        "doctype": "Baton AI Model",
        "model_name": "Default",
        "enabled": 1,
        "is_default": 1,
        "purpose": "General",
        "provider": "OpenAI Compatible",
        "base_url": base,
        "model": model,
        "temperature": 0,
        "max_tokens": 2048,
        "timeout": 90,
    })
    key = s.get_password("ai_api_key", raise_exception=False)
    if key:
        doc.api_key = key
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    print(f"  + migrated Baton Settings -> Baton AI Model 'Default' ({model})")


def install_all():
    install()
    migrate_settings_to_model()


def _add_fields(doctype, fields, insert_after=None):
    """Append fields to one of our own DocTypes if they are missing."""
    dt = frappe.get_doc("DocType", doctype)
    existing = {f.fieldname for f in dt.fields}
    added = []
    for f in fields:
        if f["fieldname"] in existing:
            continue
        dt.append("fields", f)
        added.append(f["fieldname"])
    if added:
        dt.save(ignore_permissions=True)
        print(f"  + {doctype}: {', '.join(added)}")
    else:
        print(f"  = {doctype} (all fields present)")


def _extend_select(doctype, fieldname, options):
    """Add Select options without dropping existing ones."""
    dt = frappe.get_doc("DocType", doctype)
    for f in dt.fields:
        if f.fieldname == fieldname:
            current = [o for o in (f.options or "").split("\n") if o]
            new = [o for o in options if o not in current]
            if new:
                f.options = "\n".join(current + new)
                dt.save(ignore_permissions=True)
                print(f"  + {doctype}.{fieldname} options: {', '.join(new)}")
            else:
                print(f"  = {doctype}.{fieldname} (options present)")
            return
    print(f"  ! {doctype}.{fieldname} not found")


def upgrade_workflow_schema():
    """Durable waits, event triggers and per-node retry policy."""

    # Spec §107: a run waiting three days must persist, not hold a worker.
    _add_fields("Baton Workflow Run", [
        {"fieldname": "sec_resume", "fieldtype": "Section Break", "label": "Resumption"},
        {"fieldname": "resume_at", "fieldtype": "Datetime", "label": "Resume at",
         "description": "Scheduler wakes this run when due."},
        {"fieldname": "resume_node", "fieldtype": "Data", "label": "Resume at node"},
        {"fieldname": "col_resume", "fieldtype": "Column Break"},
        {"fieldname": "attempt", "fieldtype": "Int", "label": "Attempt", "default": "1"},
        {"fieldname": "cancelled_reason", "fieldtype": "Small Text", "label": "Cancelled because"},
    ])

    # Spec §35: workflows can subscribe to bus events, not just doc events.
    _extend_select("Baton Workflow", "trigger_type", ["Event"])
    _add_fields("Baton Workflow", [
        {"fieldname": "trigger_event_name", "fieldtype": "Data", "label": "Event name",
         "depends_on": "eval:doc.trigger_type=='Event'",
         "description": "e.g. lead.replied, deal.stalled (see baton.events.EVENTS)"},
    ])

    # Spec §108: retry with backoff, and a configurable failure path.
    _add_fields("Baton Workflow Node", [
        {"fieldname": "max_retries", "fieldtype": "Int", "label": "Max retries", "default": "0"},
        {"fieldname": "retry_delay", "fieldtype": "Int", "label": "Retry delay (s)", "default": "30"},
        {"fieldname": "on_error", "fieldtype": "Select", "label": "On error",
         "options": "Fail run\nContinue\nGo to fallback", "default": "Fail run"},
        {"fieldname": "fallback_node", "fieldtype": "Data", "label": "Fallback node",
         "depends_on": "eval:doc.on_error=='Go to fallback'"},
    ])

    frappe.db.commit()
    print("Workflow schema upgraded.")
