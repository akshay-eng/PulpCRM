# Baton — AI CRM Implementation Plan

> **Companion to** [`AI_CRM_ARCHITECTURE.md`](./AI_CRM_ARCHITECTURE.md). Read
> that first — this plan is a **delta** against what already exists, not a
> restatement of the master spec.
> **Date**: 2026-08-20

---

## 0. Decisions already locked

| Decision | Choice | Consequence |
|---|---|---|
| Namespace | Keep the `baton` app and `Baton *` DocTypes | Spec's `AI *` names are descriptive. No rename migration |
| Core fork | `crm` source stays untouched except `router.js` + `AppSidebar.vue` | Upstream stays mergeable |
| Credentials on hand | LLM API key ✅ · WhatsApp Business ✅ · **Meta Ads token ❌** | Phases 3/4/6 verifiable live; Phase 2 against fixtures |
| Licence | AGPL-3.0 understood; proceeding | Settle with counsel before selling |

### How this plan differs from spec §122

Spec §122 orders the phases Architecture → Ingestion → Communication →
Qualification → Monitoring → **Human intervention** → Agent builder →
Observability.

**Two deviations, both argued from the audit:**

1. **Human intervention moves from Phase 6 to Phase 3.** The mechanism is
   already half-built (`baton_author`, `cancel_queued_followups`), and it is the
   one feature whose absence actively damages a customer relationship — an AI
   message landing after a human has already replied. It must ship *with* the
   first outbound automation, not three phases later. Shipping outbound
   automation without it would be shipping the bug.
2. **Ingestion (Phase 2) drops behind Communication (Phase 3)** because there is
   no Meta token yet, and because ingestion largely exists. Phase 2 becomes
   "harden and generalise", which is lower risk than it sounds.

Revised order: **1 → 3 → 4 → 2 → 5 → 7 → 8**, with human intervention folded
into 3.

---

## Phase 1 — Foundation

**Goal**: the spine every later phase logs and resumes through.

| Work | Detail |
|---|---|
| Durable waits (§107) | Add `resume_at` + `WAITING` to `Baton Workflow Run`; scheduler wakes due runs. Today `Wait` records intent and continues — workflows cannot actually pause |
| `Baton Action Log` (§45) | timestamp, actor type (`HUMAN`/`AI_AGENT`/`SYSTEM`/`CONNECTOR`/`MCP`), action, input, output, lead, deal, workflow, node, model, latency, success, error, external message ID |
| Idempotency (§49) | `idempotency_key` unique index; helper wrapping every outbound side effect |
| Event bus (§35) | thin `baton.events.emit(name, **ctx)` over `frappe.enqueue`; workflows subscribe by event name |
| Retry policy (§108) | per-node `max_retries`, backoff, retryable vs terminal errors |
| Tests | **the existing engine has none** — backfill `safe_eval` conditions, branch selection, cycle guard, run-history integrity |

**Files**: `baton/events.py` (new), `baton/workflow/engine.py`,
`baton/baton/doctype/baton_action_log/` (new), `baton/hooks.py`

**Risk**: the `"*"` doc_events hook fires on every document save site-wide. It
currently short-circuits on an indexed lookup, but must be benchmarked before
volume — a slow path here slows the entire CRM.

**Done when**: a workflow can wait 3 days across a bench restart and resume; every
outbound action writes exactly one log row even when retried.

---

## Phase 3 (next) — AI communication + human handoff

**Goal**: Baton holds a real WhatsApp conversation and always yields to a human.
Verifiable now — both credentials are in hand.

### 3a Conversation abstraction (§64–65)

One read model over two stores, so the agent is channel-agnostic:

```
Conversation
   ├── Communication      (email, native)
   └── WhatsApp Message   (frappe_whatsapp)
```

A view/service — **not** a new message table. Copying messages into a third table
would desynchronise from the CRM timeline.

### 3b Per-purpose model config (§11)

Extend `Baton Settings` from one model to a child table: purpose
(`qualification` / `conversation` / `summarisation` / `workflow`), provider, base
URL, model, temperature, max tokens, timeout, retries. Keys stay in `Password`
fields, never returned to the frontend.

### 3c Follow-up engine (§15–17)

Configurable ladder — no hardcoded "2 days". Channel order, max attempts, quiet
hours (§51), timezone. **A lead response cancels pending follow-ups** — extend the
existing `cancel_queued_followups`.

### 3d Human handoff state machine (§26–28) — pulled forward

```
AI_ACTIVE ──human outbound──▶ HUMAN_ACTIVE ──cooldown──▶ AI_REVIEW_PENDING ──▶ AI_ACTIVE
```

States: `AI_ACTIVE`, `HUMAN_ACTIVE`, `PAUSED`, `ESCALATED`, `CLOSED`,
`DO_NOT_CONTACT`. Cooldown configurable (15m/1h/6h/12h/24h/custom). Resume policy
`AUTO_RESUME` / `REQUIRE_APPROVAL` / `REMAIN_PAUSED`.

The detection half exists: `baton/api/whatsapp.py::tag_author` marks any
unclaimed outbound as `human`. What is missing is the state, the cooldown timer,
and the check at send time.

### 3e Template / 24-hour window gating (§14)

Outside Meta's 24-hour service window, free-form is refused and an approved
template is required. The engine must know which branch applies **before**
composing, or it will compose messages that cannot be sent.

### 3f Draft mode + approval gates (§58–59)

`Baton Approval` exists as a DocType with no UI and no engine gate. Add both.
Recommend **draft mode ON by default** for a first customer.

**Files**: `baton/conversation/` (new), `baton/agents/conversation.py` (new),
`baton/api/whatsapp.py`, `baton/workflow/engine.py`,
`frontend/src/components/Activities/` (approval UI)

**Test scenarios** — spec §80, §81, §83, §84:
- human message → AI pauses → **no AI message during cooldown**
- human replies at 12:00 while a follow-up is queued for 14:00 → **14:00 send is
  cancelled**, not merely delayed
- worker retry after timeout → no duplicate customer message
- WhatsApp API failure → retry, then configurable fallback to email

**Done when**: §123's Communication and Human-intervention checklists pass, and
the §81 wait-window edge case has a test.

---

## Phase 4 — Qualification and deals

| Work | Detail |
|---|---|
| `Baton Qualification Profile` (§18) | field, question, required, priority, weight, acceptable values, rejection rules, threshold — all configurable |
| `Baton Qualification Result` (§20) | score, summary, budget, timeline, decision maker, objections, confidence, source conversation |
| Scoring (§19) | weights and bands (`Cold`/`Warm`/`Qualified`/`Hot`) configurable, **not hardcoded** |
| Conversion (§21) | **call `crm.fcrm.doctype.crm_lead.crm_lead.convert_to_deal`** — do not reimplement; it handles permissions, Contact, Organization, custom-field mapping |
| Assignment (§22) | native `Assignment Rule` via `crm/api/assignment_rule.py` |
| Owner notification (§23) | `CRM Notification` + WhatsApp + email, with the §113 handoff brief |

> **Naming**: `crm/install.py:88` already ships a `CRM Deal Status` called
> **"Qualification"** (the first pipeline stage) and a `CRM Lead Status` called
> "Qualified". Baton's DocTypes therefore keep the `Baton ` prefix, and UI labels
> should read "lead scoring" to avoid colliding with the pipeline stage.

**Risk**: extraction quality. Mitigate with structured JSON output (`chat_json`
already does this) and a confidence threshold below which it routes to human
review rather than auto-converting.

**Done when**: a conversation drives a score, crosses the threshold, and produces
**exactly one** Deal with the qualification summary attached.

---

## Phase 2 (deferred) — Ingestion hardening

Deferred because it largely exists and the Meta token is missing. Verified
against **recorded fixtures** until a token arrives.

| Work | Detail |
|---|---|
| Generic provider fields (§6) | `external_source`, `external_source_id`, `external_lead_id`, `campaign_id/name`, `adset_id/name`, `ad_id/name`, `form_id/name`, `raw_payload` as custom fields on `CRM Lead` |
| Normalisation (§7) | E.164 phones, lowercased emails, name splitting — pure functions, unit-tested |
| **Rewrite dedupe** (§8) | match on external lead ID → normalised email → normalised phone → composite. Flag `Possible duplicate lead` when confidence is low. **Never destroy data** |
| Connector interface (§40) | `authenticate/validate/trigger/poll/receive/send/execute`; generalise `Lead Sync Source` beyond Facebook |
| Generic REST connector (§41) | URL, method, headers, auth, response mapping, pagination |
| Webhook + reconciliation (§118) | assume webhooks drop messages; polling reconciles without duplicating |
| **HMAC on the WhatsApp webhook (§73)** | ⚠️ carried from Finding 1 — `X-Hub-Signature-256` via `hmac.compare_digest`, as a `baton` override, not an edit to the vendored app |

**Do not remove** `facebook_lead_id`/`facebook_form_id` — existing rows use them.
Backfill the generic fields and keep both (§99/§100).

**Done when**: the same Meta payload delivered twice yields exactly one Lead
(§82), and a bad signature is rejected.

---

## Phase 5 — Deal monitoring

Deal health score (§31) with configurable dimensions and bands; task monitoring
(§32); contextful reminders (§33 — never "Reminder: task overdue"); escalation
ladder (§34) with configurable thresholds.

Anchors on the existing `CRM Task` and the activity timeline in
`crm/api/activities.py`.

---

## Phase 7 — Agent builder, connectors, MCP

`Baton Agent` (§56, §61): model, system prompt, enabled tools, connectors, MCP
servers, permissions, workflows. Explicit capability grants (§57) —
`READ_LEAD`, `SEND_WHATSAPP`, `CREATE_DEAL`… — checked at call time (§96), never
implicit.

MCP layer (§39): server registry, transport, auth, per-agent tool allowlists.
**Tools are opt-in per agent** — discovery must not equal permission.

Prompt versioning (§86) and workflow versioning (§85): a running execution stays
pinned to the version it started on.

Extends the existing Vue Flow canvas rather than replacing it.

---

## Phase 8 — Observability

Automation dashboard (§53), execution drill-down (§74), categorised error monitor
(§75).

The §74 acceptance test is the real bar: a user must be able to answer *"why
didn't the AI send the WhatsApp message?"* and get

```
Workflow started → Lead qualified → Wait scheduled → Wait completed
→ WhatsApp attempted → policy check → human intervention detected
→ action cancelled → conversation moved to HUMAN_ACTIVE
```

That trace is only possible if Phase 1's action log is honest from the start.

---

## Cross-cutting requirements

| Requirement | Where |
|---|---|
| Configuration over code (§87) | every threshold, delay, weight and band is a DocType field. No magic numbers |
| Security (§69) | secrets in `Password` fields; never to the frontend, logs, or prompts |
| No arbitrary code execution (§98) | `frappe.safe_eval` with a fixed pure-builtin globals set. Already how the engine works |
| No AI-authored SQL (§97) | already enforced — `baton/api/chat.py` validates a query spec and calls `frappe.get_list` |
| Multi-tenancy (§70) | no module-level mutable state for tenant data |
| Performance (§105) | indexes on external IDs, email, phone, status, `resume_at` |

---

## Testing strategy

**Unit**: normalisation, dedupe, scoring, state transitions, cooldown maths,
workflow conditions, variable interpolation, idempotency keys.

**Integration** (§77–84): Meta payload → Lead (exactly one); lead reply cancels
follow-up; qualified lead → exactly one Deal; overdue task → reminder; human
WhatsApp → AI pause.

**The two that matter most**, because they are the ones a demo will expose:
- **§81** — human replies during a scheduled wait; the later action must be
  cancelled, not merely deferred
- **§82** — duplicate webhook yields one Lead

**Command**: `bench --site crm.localhost run-tests --app baton`

---

## Definition of done (§123)

Tracked per phase:

| Checklist | Phase |
|---|---|
| Lead ingestion | 2 |
| AI (model, agent, permissions, context, logging) | 1, 3, 7 |
| Communication | 3 |
| Qualification | 4 |
| Deal | 4, 5 |
| Human intervention | **3** (pulled forward) |
| Workflow (incl. retry, versioning) | 1, 7 |
| Agent builder | 7 |
| Reliability | 1, 2 |

---

## Open items blocking Phase 1

1. **Meta access token** — until then Phase 2 is fixture-verified only.
2. **Model per purpose** (§11) — which provider/model for qualification vs
   conversation vs summarisation.
3. **Cooldown default and resume policy** (§28) — recommend 6h +
   `REQUIRE_APPROVAL` for a first customer.
4. **Draft mode default** (§59) — recommend ON; it shapes the approval UI, so
   decide before Phase 3 starts.
5. **Business knowledge source** (§110–111) — the guardrail against invented
   pricing. Without it, the conversation agent must refuse commercial questions
   and escalate.
