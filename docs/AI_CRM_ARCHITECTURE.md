# Baton — AI CRM Architecture Audit

> **Status**: audit only. No code was changed to produce this document.
> **Date**: 2026-08-20
> **Purpose**: establish what already exists before any AI automation is built,
> so we do not rebuild working functionality (master spec §119).

Every claim below cites a file. Where a spec section is already satisfied by
existing code, the citation is the point — not the prose.

---

## 1. Repository identity

Determined from the running bench, not assumed.

| App | Version | Branch | Licence |
|---|---|---|---|
| `frappe` | 15.118.0 | `version-15` | MIT (`apps/frappe/LICENSE`) |
| `crm` | 1.81.2 | `main` | **AGPL-3.0** (`apps/crm/LICENSE`) |
| `frappe_whatsapp` | 1.0.12 | `master` | MIT |
| `baton` | 0.0.1 | — | our app |

`crm` is on `main`, not `develop`. This matters: `develop`'s `pyproject.toml`
declares `frappe = ">=16.0.0-dev,<=17.0.0-dev"`, so it will not run on the
Frappe v15 installed here. `main` declares `frappe = ">=15.0.0,<17.0.0"`.

`frappe_whatsapp` is a third-party app by `shridarpatil`, not the Frappe
organisation, though Frappe CRM references it by name in
`crm/api/whatsapp.py`.

---

## 2. Existing architecture

Two frontends share one backend:

| Path | What it is |
|---|---|
| `/crm` | The product UI. Vue 3 + frappe-ui, source under `frontend/`, built into `crm/public/frontend/` |
| `/app` | Frappe's generic admin desk, auto-generated from DocType schemas |

`AGENTS.md` states the split plainly: *"Scripts in `frontend/` only; Python in
`crm/` (Frappe app)."*

**Product implication**: customers should never be sent to `/app`. Any Baton
feature intended for end users must be built as a Vue page under `frontend/src/`
and routed in `frontend/src/router.js`.

The repo also carries its own working notes in `.pi/` — `PLAN.md`, `SPEC.md`,
`ARCHIVE.md` — describing an in-flight Form Scripting refactor. Worth reading
before touching `frontend/src/data/document.js` or the `FieldLayout` components,
which that refactor is actively restructuring.

---

## 3. Existing DocTypes

40 DocTypes under `crm/fcrm/doctype/`. Grouped by role:

| Role | DocTypes |
|---|---|
| Core records | `crm_lead`, `crm_deal`, `crm_organization`, `crm_contacts`, `fcrm_note`, `crm_task` |
| Pipeline vocabulary | `crm_lead_status`, `crm_deal_status`, `crm_lead_source`, `crm_industry`, `crm_territory`, `crm_lost_reason` |
| SLA | `crm_service_level_agreement`, `crm_service_level_priority`, `crm_rolling_response_time`, `crm_holiday`, `crm_holiday_list`, `crm_service_day` |
| Telephony | `crm_telephony_agent`, `crm_telephony_phone`, `crm_twilio_settings`, `crm_exotel_settings`, `crm_call_log` |
| UI config | `crm_fields_layout`, `crm_view_settings`, `crm_form_script`, `crm_dashboard`, `crm_dropdown_item` |
| Products | `crm_product`, `crm_products`, `crm_product_sync_issue` |
| Ops | `crm_notification`, `crm_status_change_log`, `crm_invitation`, `crm_global_settings`, `fcrm_settings`, `crm_communication_status`, `crm_sales_hierarchy`, `erpnext_crm_settings` |

Separately, `crm/lead_syncing/doctype/` holds `lead_sync_source`,
`facebook_page`, `facebook_lead_form`, `facebook_lead_form_question`,
`failed_lead_sync_log`.

---

## 4. Lead and Deal lifecycle

**Lead → Deal conversion already exists and is thorough.**
`crm/fcrm/doctype/crm_lead/crm_lead.py:489` `convert_to_deal()`:

1. checks `frappe.has_permission("CRM Lead", "write", lead)`
2. sets status `Qualified` and `converted = 1`
3. sets `communication_status = Replied` when an SLA applies
4. creates Contact (`create_contact`), Organization (`create_organization`), Deal (`create_deal`)
5. maps fields through `LEAD_DEAL_FIELD_MAP`, plus `get_matching_custom_deal_field()`
   which matches custom fields by label + fieldtype

Spec §21 says to extend this rather than build a parallel deal system. **Phase 4
must call this function.** Reimplementing it would lose the custom-field mapping
and the permission check.

**First-response SLA is native.** `CRM Lead` already carries `sla`,
`sla_creation`, `sla_status`, `response_by`, `first_response_time`,
`communication_status`, `rolling_responses`, `last_response_time`. Anything the
spec implies about response-time tracking is largely already present.

---

## 5. Communication mechanism

Email uses Frappe's core `Communication` DocType, linked to CRM records by
`reference_doctype` / `reference_name`. Hooked in `crm/hooks.py`:

```python
"Communication": {
    "after_insert": ["crm.utils.on_communication_insert"],
    "on_update":    ["crm.utils.on_communication_update"],
}
```

`crm/utils/__init__.py` restricts handling to `["CRM Lead", "CRM Deal"]` and —
notably — **auto-creates a Lead from an inbound email** when the sender matches
no existing lead (`crm/utils/__init__.py:214-233`), tagging it with the
`Email` lead source and setting `reference_doctype = "CRM Lead"`.

**Implication**: an email ingestion channel already exists. Spec §13's email
automation should attach to `Communication`, not invent a new message table.

---

## 6. WhatsApp implementation

`crm/api/whatsapp.py` (387 lines) provides `get_whatsapp_messages`,
`create_whatsapp_message`, `send_whatsapp_template`, `react_on_whatsapp_message`,
`is_whatsapp_enabled`, `is_whatsapp_installed`.

The UI is `frontend/src/components/Activities/WhatsAppArea.vue` and
`WhatsAppBox.vue`. The tab in `frontend/src/pages/Lead.vue:461` is gated on:

```js
condition: () => whatsappEnabled.value
```

which resolves via `frontend/src/composables/whatsapp.js` → `crm.api.whatsapp.is_whatsapp_enabled`.
That returns true only when `WhatsApp Settings.default_outgoing_account` points at
a `WhatsApp Account` whose `status == "Active"`.

Message doc events are already hooked:

```python
"WhatsApp Message": {
    "validate":  ["crm.api.whatsapp.validate"],
    "on_update": ["crm.api.whatsapp.on_update"],
}
```

`frappe_whatsapp` supplies 15 DocTypes including `whatsapp_message`,
`whatsapp_templates`, `whatsapp_account`, `whatsapp_settings`,
`whatsapp_notification`, `whatsapp_flow`.

### ⚠️ Finding 1 — the inbound webhook is unauthenticated

`frappe_whatsapp/utils/webhook.py:13`:

```python
@frappe.whitelist(allow_guest=True)
def webhook():
    if frappe.request.method == "GET":
        return get()
    return post()
```

`get()` validates `hub.verify_token` against a `WhatsApp Account`. **`post()`
validates nothing.** It writes the payload to `WhatsApp Notification Log` and
processes messages directly. There is no `X-Hub-Signature-256` check, no shared
secret, no replay protection.

HMAC verification does exist in the app — but only for WhatsApp Flows, at
`frappe_whatsapp/frappe_whatsapp/api/flow_endpoint.py:140` (`verify_signature`,
using `hmac.compare_digest`). It is not applied to the message webhook.

This directly violates master spec §73 ("signature verification... replay
protection... Never trust arbitrary webhook payloads"). Anyone who learns the
endpoint URL can inject fabricated inbound messages, which in an AI-automated
system means driving the agent's behaviour.

**Recommended fix** (scheduled, not applied): verify `X-Hub-Signature-256`
against the Meta app secret with `hmac.compare_digest`, implemented as an
override in `baton` rather than by editing the vendored app, so upgrades of
`frappe_whatsapp` do not silently drop the check.

---

## 7. Lead ingestion — Meta Lead Ads is already native

`crm/lead_syncing/` implements Facebook/Meta Lead Ads ingestion:

| File | Role |
|---|---|
| `doctype/lead_sync_source/lead_sync_source.json` | connector config: `type`, `access_token`, `facebook_page`, `facebook_lead_form`, `enabled`, `background_sync_frequency`, `last_synced_at` |
| `doctype/lead_sync_source/facebook.py` | Graph API client: `fetch_leads`, `sync`, `sync_single_lead`, `fetch_and_store_pages_from_facebook` |
| `doctype/facebook_page/` | Pages discovered from `/me/accounts` |
| `doctype/facebook_lead_form/` + `_question/` | forms and their field mapping |
| `doctype/failed_lead_sync_log/` | failure record |
| `background_sync.py` | scheduler entry points |

It is **polling, not webhook** — driven from `crm/hooks.py`:

```python
"daily_long":   ["...sync_leads_from_sources_daily"],
"hourly_long":  ["...sync_leads_from_sources_hourly"],
"cron": {
    "*/5 * * * *":  ["...sync_leads_from_sources_5_minutes"],
    "*/10 * * * *": ["...sync_leads_from_sources_10_minutes"],
    "*/15 * * * *": ["...sync_leads_from_sources_15_minutes"],
}
```

Polling has a real advantage for us: **no public URL required**, so it works from
a laptop without a tunnel.

There is a settings UI at `frontend/src/components/Settings/LeadSyncing/`
(`LeadSyncSources.vue`, `LeadSyncSourceForm.vue`, `FailureLogs.vue`).

### Gap 7a — deduplication is weak and provider-specific

`facebook.py::validate_duplicate_lead`:

```python
validation_filters = {crm_field: lead_data[crm_field] for crm_field in field_mapping.values()}
validation_filters["facebook_form_id"] = lead_data["facebook_form_id"]
if frappe.db.exists("CRM Lead", validation_filters):
    raise DuplicateLeadError
```

It matches on **every mapped field** plus the form ID. If the same person
resubmits with one character different, it is not a duplicate. There is no
normalised-email or normalised-phone matching, and nothing cross-provider.

Spec §8 requires matching on provider lead ID, email, normalised phone, WhatsApp
number, and configurable composite keys, with a `Possible duplicate lead` state
rather than destructive merging.

### Gap 7b — no generic provider metadata

`CRM Lead` carries only `facebook_lead_id` and `facebook_form_id`. Spec §6
requires `external_source`, `external_source_id`, `external_lead_id`,
`campaign_id`, `campaign_name`, `adset_id`, `adset_name`, `ad_id`, `ad_name`,
`form_id`, `form_name`, `raw_payload`.

Without `raw_payload` we are discarding provider data permanently, which §7
forbids.

---

## 8. Assignment

Frappe's core `Assignment Rule` is already wired: `crm/api/assignment_rule.py`
exposes `get_assignment_rules_list()` filtered to `["CRM Lead", "CRM Deal"]`, and
`duplicate_assignment_rule()`. UI at `frontend/src/components/Settings/AssignmentRules/`.

Frappe's own rule engine supports round-robin and load-balancing. Spec §22 says
to integrate with this rather than build another mechanism.

---

## 9. Background jobs and scheduler

Frappe queues (`short`, `default`, `long`) plus `scheduler_events` in
`crm/hooks.py`. `bench start` runs `schedule` and `worker` processes via the
Procfile.

`baton/workflow/engine.py` already uses `frappe.enqueue(..., queue="short")` for
document-event triggers, satisfying spec §43's "do not run AI synchronously in
HTTP requests" for that path.

**Gap**: spec §107 requires durable waits — a workflow waiting three days must
persist `resume_at` and be woken by the scheduler. The current engine's `Wait`
node explicitly does *not* block, but also does not reschedule; it records the
intent and moves on.

---

## 10. Notifications

`CRM Notification` DocType plus `crm/api/notifications.py`
(`get_notifications`, `mark_as_read`). WhatsApp notifications hash on
`#whatsapp` (`crm/api/notifications.py:63`).

Spec §23's owner notification can write `CRM Notification` rows and reuse the
existing bell UI rather than inventing a channel.

---

## 11. Permissions

Frappe roles, plus a CRM-specific organisation hierarchy in
`crm/permissions/org_hierarchy.py` (tested in `test_org_hierarchy.py`) and the
`CRM Sales Hierarchy` DocType.

This is the enforcement point spec §57 and §96 must defer to. The existing Baton
chat already does this correctly — `baton/api/chat.py` calls `frappe.get_list`,
not `get_all`, so row-level permissions apply to AI-retrieved data.

---

## 12. Frontend routing

Routes in `frontend/src/router.js`; sidebar entries in
`frontend/src/components/Layouts/AppSidebar.vue` (the `links` array).

Baton added `/workflows` and `/workflows/:workflowId` plus a `Workflows` sidebar
entry. **These are the only modifications to `crm` source**; everything else in
Baton lives in its own app.

---

## 13. Existing tests

44 `test_*.py` files. Relevant ones: `crm/tests/test_whatsapp.py`,
`crm/tests/test_integrations.py`, `crm/tests/test_utils.py`,
`crm/permissions/test_org_hierarchy.py`, and the `lead_syncing` DocType tests.
`before_tests = "crm.tests.before_tests"` in `crm/hooks.py`.

Baton currently has **no tests** — its DocType test stubs are the generated
empty ones. This is the single largest quality gap in what we have written.

---

## 14. Telephony

Two providers, working differently:

| | Twilio | Exotel |
|---|---|---|
| DocType | `crm_twilio_settings` | `crm_exotel_settings` |
| Credentials | `account_sid`, `auth_token`, `api_key`, `api_secret`, `twiml_sid` | `account_sid`, `api_key`, `api_token`, `subdomain`, `webhook_verify_token` |
| Mechanism | Browser WebRTC via `@twilio/voice-sdk` | Server-side click-to-call (`Calls/connect.json`) |
| Agent setup | — | `CRM Telephony Agent.mobile_no` + `.exotel_number` |

Exotel rings the agent's own phone then bridges — better suited to a mobile-first
Indian sales team. Both require a publicly reachable callback URL;
`crm/integrations/exotel/handler.py:150` builds it from `frappe.utils.get_url()`,
which on `localhost` is unreachable from the provider.

Spec §66 defers AI voice; the existing `CRM Call Log` is the natural anchor when
it arrives.

---

## 15. What `baton` already adds

Installed as a separate app (`apps/baton`), so `crm` stays upgradable.

| DocType | Purpose |
|---|---|
| `Baton Settings` | single: AI provider (OpenAI-compatible base URL, model, key), `ai_max_rows`, `ai_turn_cap`, `agent_signature` |
| `Baton Workflow` + `Baton Workflow Node` | graph definition; trigger type, doctype, event, cron, condition |
| `Baton Workflow Run` + `Run Step` | per-execution history with per-node output and duration |
| `Baton Approval` | pending human decision, with `costs_template` and expiry |
| `Baton Chat Session` + `Baton Chat Message` | AI data chat, storing the query spec used |

Code:

| File | Role |
|---|---|
| `baton/workflow/engine.py` | executes graphs; 10 node types; `frappe.safe_eval` conditions with an extended pure-builtin globals set; `MAX_STEPS` cycle guard |
| `baton/workflow/scheduler.py` | per-minute cron matcher for scheduled workflows |
| `baton/llm.py` | provider-agnostic OpenAI-compatible client (`chat`, `chat_json`) |
| `baton/api/chat.py` | natural-language → **validated query spec** → `frappe.get_list`; never SQL |
| `baton/api/whatsapp.py` | `tag_author`, `cancel_queued_followups` |
| `baton/api/workflow.py` | CRUD + action catalogue for the canvas |
| `frontend/src/pages/Workflow.vue` | Vue Flow canvas |

**The `baton_author` field is the important one.** A custom field on
`WhatsApp Message` with options `contact | human | ai`, set in `before_insert` so
nothing can write a message without it. `cancel_queued_followups` then withdraws
pending AI approvals when a human replies — the mechanism spec §25–29 describes,
though not yet the full state machine.

---

## 16. Reconciliation — spec section by section

| Spec | Status | Evidence |
|---|---|---|
| §5–6 Lead ingestion, Meta | **Exists native** | `crm/lead_syncing/`, scheduler cron |
| §6 Provider metadata | **Partial** | only `facebook_lead_id`, `facebook_form_id`; no `raw_payload` |
| §7 Normalisation | **New** | no normalisation layer |
| §8 Deduplication | **Partial, weak** | `facebook.py::validate_duplicate_lead` |
| §9–10 Orchestrator, specialised agents | **New** | — |
| §11 Model configuration | **Partial** | `Baton Settings`, single model; §11 wants per-purpose |
| §12 Context engine | **Partial** | `baton/api/chat.py::_catalog` builds bounded context |
| §13 Email automation | **Partial** | `Communication` + hooks exist; no automation |
| §14 WhatsApp | **Exists** | `frappe_whatsapp` + `crm/api/whatsapp.py` |
| §15–17 Follow-up engine, response detection | **New** | — |
| §18–20 Qualification | **New** | see naming warning below |
| §21 Lead → Deal | **Exists native** | `crm_lead.py:489` |
| §22 Assignment | **Exists native** | `crm/api/assignment_rule.py` |
| §23 Owner notification | **Partial** | `CRM Notification` exists |
| §25–29 Human intervention | **Partial, built** | `baton_author`, `cancel_queued_followups` |
| §30–34 Deal health, task monitoring, escalation | **New** | — |
| §35 Event bus | **New** | doc_events only |
| §36–37 Workflow engine + builder | **Exists in baton** | `engine.py`, Vue Flow canvas |
| §38 Variables | **Partial** | `{{ doc.x }}` via `frappe.render_template` |
| §39 MCP | **New** | — |
| §40–42 Connectors, REST, polling | **Partial** | Facebook-only; scheduler polling exists |
| §43 Background processing | **Exists native** | Frappe queues |
| §44–47 Execution/action log, audit, decision trace | **Partial** | `Workflow Run` + `Run Step`; no action log |
| §48 Failsafe | **Partial** | engine try/except + `frappe.log_error` |
| §49 Idempotency | **New** | — |
| §50–52 Rate limits, quiet hours, consent | **New** | — |
| §53 Dashboard | **New** | — |
| §54–56 Lead/Deal AI panels, agent control | **New** | — |
| §57 Tool permissions | **Partial** | chat allowlist + `get_list` |
| §58–59 Approval gates, draft mode | **Partial** | `Baton Approval` DocType only |
| §60 Global switch | **Partial** | `Baton Settings.ai_enabled` |
| §73 Webhook security | **❌ Broken** | see Finding 1 |
| §85–86 Versioning | **New** | — |
| §99–100 Migration, back-compat | **Holds** | `crm` source untouched but for 2 files |

### ⚠️ Naming collision — "Qualification" is already taken

`crm/install.py:88` `add_default_deal_statuses()` creates a **`CRM Deal Status`
named "Qualification"** (probability 10, the first pipeline stage). There is also
a `CRM Lead Status` named "Qualified", which `convert_to_deal()` sets.

Neither is a scoring system — a `grep` for "qualification" across `crm/` returns
only this stage name, demo data and dashboard counts. So spec §18–20 really is
new work.

But the name is occupied. Baton's DocTypes must be `Baton Qualification Profile`
and `Baton Qualification Result` to avoid ambiguity with the pipeline stage, and
any UI label should say "lead scoring" rather than bare "Qualification".

---

## 17. Proposed extension architecture

The layering spec §120 asks for, mapped onto real modules:

```
CRM Domain          crm/fcrm/doctype/*          (unmodified)
      |
Automation Domain   baton/baton/doctype/*
      |
Workflow Engine     baton/workflow/engine.py
      |
Agent Runtime       baton/agents/*              (new)
      |
Connector Layer     baton/connectors/*          (new, generalising crm/lead_syncing)
      |
Channel Adapters    baton/channels/*            (new: email → Communication, wa → WhatsApp Message)
```

Dependencies point downward only. `crm` never imports `baton`; `baton` declares
`required_apps = ["crm"]` in `baton/hooks.py`.

Two rules that follow from this audit:

1. **Never fork what can be hooked.** The only `crm` edits are `router.js` and
   `AppSidebar.vue`. Each is a future merge conflict; keep the count near zero.
2. **Extend, don't parallel.** Deals come from `convert_to_deal()`, assignment
   from `Assignment Rule`, email from `Communication`, notifications from
   `CRM Notification`. Baton adds intelligence, not replacements.

---

## 18. Licence position

### ⚠️ Finding 2 — Frappe CRM is AGPL-3.0

`apps/crm/LICENSE` is the stock GNU **Affero** General Public License v3, with
§13 *Remote Network Interaction* intact and no additional-permission carve-out.
GitHub's licence detection reports `AGPL-3.0` for `frappe/crm`.

`package.json` declares `"license": "GPL-3.0"`. This conflicts with the LICENSE
file. The LICENSE file governs.

The distinction is material because Baton is to be sold as hosted software:

| | GPL-3.0 | AGPL-3.0 |
|---|---|---|
| Sell commercially | yes | yes |
| Modify privately, offer as SaaS | no disclosure | **§13: offer source to your users** |

Unlike Twenty — which grants an Application Exception permitting proprietary
apps built on published interfaces — Frappe CRM grants no such exception.

The owner has reviewed this and elected to proceed. It is recorded here as a
business risk to settle with counsel, not an engineering blocker. Note also that
"Frappe" is a trademark, so the product must ship under its own name and must
not imply endorsement.

---

## 19. Summary — the five things that matter

1. **Meta lead ingestion, SLA, assignment, lead→deal conversion, email linking
   and the WhatsApp tab already exist.** The spec's Phases 2, 4 and much of 3 are
   substantially pre-built. The real work is orchestration, qualification and
   observability.
2. **The WhatsApp inbound webhook has no authentication.** Fix before any public
   deployment.
3. **Deduplication is too weak to trust** and provider metadata is discarded.
   Both are prerequisites for multi-source ingestion.
4. **Baton already has a tested workflow engine and canvas** — but no tests of
   its own, no durable waits, no idempotency, no action log.
5. **Frappe CRM is AGPL-3.0**, and the product is to be sold hosted.
