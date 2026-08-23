app_name = "baton"
app_title = "Baton"
app_publisher = "PulpLabs"
app_description = "Lead to cash, one thread. WhatsApp-first layer over Frappe CRM."
app_email = "akshaysdeekshith@gmail.com"
app_license = "mit"

required_apps = ["crm"]

# ---------------------------------------------------------------------------
# Document events
#
# The "*" listener is what makes the workflow builder work on any doctype
# without registering each one. handle_document_event returns immediately
# unless a workflow is actually listening for that doctype+event pair, so the
# cost on unrelated saves is one indexed lookup.
# ---------------------------------------------------------------------------
doc_events = {
    "*": {
        "after_insert": [
            "baton.workflow.engine.handle_document_event",
            "baton.bots.runtime.handle_document_event",
            "baton.audit.record_document_event",
        ],
        "on_update": [
            "baton.workflow.engine.handle_document_event",
            "baton.bots.runtime.handle_document_event",
            "baton.audit.record_document_event",
        ],
        "on_trash": [
            "baton.workflow.engine.handle_document_event",
            "baton.bots.runtime.handle_document_event",
            "baton.audit.record_document_event",
        ],
        "after_rename": "baton.audit.record_document_event",
    },
    "WhatsApp Message": {
        "before_insert": "baton.api.whatsapp.tag_author",
        # Runs after CRM's own validate hook (baton is installed last), which
        # re-files messages by phone number. A message Baton addressed keeps the
        # record it was addressed to.
        "validate": "baton.overrides.whatsapp_message.keep_baton_reference",
        "after_insert": "baton.api.whatsapp.on_message",
    },
}

scheduler_events = {
    "cron": {
        # Scheduled workflows are polled once a minute and matched against
        # their cron expression inside the job.
        "* * * * *": [
            "baton.workflow.scheduler.tick",
            # Durable waits: wake runs whose resume_at has passed (spec §107).
            "baton.workflow.scheduler.resume_due_runs",
            # Act on conversations whose human cooldown has elapsed (spec §28).
            "baton.conversation.state.review_expired_cooldowns",
            # Recover runs whose worker died mid-node.
            "baton.workflow.scheduler.sweep_stale_runs",
            # Hand back slots a customer never confirmed.
            "baton.scheduling.book.release_expired_holds",
        ],
    },
    "daily": [
        # The action log is on the send path (already_done, the rate limit), so
        # it cannot be allowed to grow without bound.
        "baton.audit.purge_old_logs",
    ],
}



# The vendored frappe_whatsapp webhook accepts unauthenticated POSTs. Replace it
# with a signature-verifying wrapper without editing that app, so an upgrade
# cannot silently remove the check.
override_whitelisted_methods = {
    "frappe_whatsapp.utils.webhook.webhook": "baton.api.webhook.webhook",
    # CRM decides whether to show its WhatsApp tab by looking for an Active
    # Meta account. OpenWA has none, so the tab needs a broader answer.
    "crm.api.whatsapp.is_whatsapp_enabled": "baton.api.whatsapp.is_whatsapp_enabled",
}

override_doctype_class = {
    # Route outgoing WhatsApp through OpenWA when configured, without editing
    # the vendored frappe_whatsapp app.
    "WhatsApp Message": "baton.overrides.whatsapp_message.BatonWhatsAppMessage",
}
