# PulpCRM — Baton

An AI sales-automation layer over [Frappe CRM](https://github.com/frappe/crm):
lead → AI qualification → multi-channel conversation → deal → assignment →
owner notification, with human handoff throughout.

Built as a **separate Frappe app**, not a fork of the CRM. Frappe CRM's source is
untouched apart from four frontend files (see `crm-fork/`), so it stays
upgradable.

---

## What works today

| Capability | Status |
|---|---|
| Node-graph workflow engine — 12 node types, branching, durable waits, retry | ✅ tested |
| Visual workflow builder in the CRM UI (`/crm/automation`, Vue Flow) | ✅ |
| Multi-provider LLM — OpenAI-compatible, Anthropic, Gemini, Ollama, Azure | ✅ tested |
| AI qualification — configurable criteria, weights, score bands | ✅ tested |
| Lead → Deal conversion, assignment, owner notification | ✅ tested |
| Human handoff state machine with cooldown and resume policy | ✅ tested |
| Natural-language data chat (permission-safe, never SQL) | ✅ tested |
| Follow-up ladder, generated as an editable workflow | ✅ |
| WhatsApp webhook signature verification (fixes an upstream hole) | ✅ tested |
| **Drag-and-drop builder** — palette, editable edges, per-node forms, live validation | ✅ |
| **Bots** — brief plus connectors, a bounded tool loop the model drives | ✅ tested |
| **CRM-shaped palette** — steps named for leads, deals, contacts, organizations | ✅ tested |
| **Scheduled bots** — cron triggers, allow-listed page reading, report-by-email | ✅ tested |
| **Google sign-in and send-as-me Gmail** — one client, both flows wired from the CRM | ✅ tested |
| **Durable waits on a customer reply** — park, resume on inbound, time out cleanly | ✅ tested |
| **Conversational agent** — three validated actions, admin-declared options and facts | ✅ tested |
| **Meeting booking** — working hours, holidays, timezones, conflict-safe holds, Google Calendar | ✅ tested |
| **Signed inbound webhooks** as a workflow trigger (fails closed) | ✅ tested |
| **OpenWA connector** — self-hosted WhatsApp bridge, HMAC-verified | ✅ live-tested |
| **Credentials in Settings** — models and channels, selected by builders, never held by them | ✅ |
| Meta Lead Ads ingestion | ⏳ native to Frappe CRM; hardening pending |
| Deal monitoring, escalation, MCP, agent builder, dashboard | ⏳ not started |

**248 tests**: `bench --site <site> run-tests --app baton`

---

## Bots and workflows

Two different things, not two names for one.

**A workflow is a graph you draw.** Trigger, step, branch, step. It does exactly
what the picture says, in that order, every time. The palette is named for the
CRM: *Set the lead status*, *Move the deal to a stage*, *Assign the lead*,
*Convert to a deal*. Use one when you can write the steps down.

**A bot is a brief you write.** Instructions, guardrails, a model, and a set of
**connectors** dragged onto the canvas around it — Leads, Deals, WhatsApp,
Calendar, Tasks. Each connector grants a few named tools; the bot decides which
to call and in what order, one step at a time, inside a hard step budget. Use one
when the right next step depends on what the customer says.

What keeps a bot safe is not the prompt:

* it may only call tools whose connector is **attached and enabled** — checked
  in code on every call, so an invented tool name gets an error string back
  rather than a dispatch
* writes go to allow-listed doctypes and never to `owner`, `docstatus`, `parent`
  or anything else structural
* everything it says goes through `workflow.actions.whatsapp.send`, the same
  single gated path a workflow uses, so human handoff, quiet hours, the turn cap
  and do-not-contact all still apply
* every decision and every tool call lands in `Baton Action Log`

Both record runs in `Baton Workflow Run`, so durable waits, claim tokens,
heartbeats, the stale-run sweeper and the inbound-reply resume are shared rather
than reimplemented.

---

## Architecture

```
CRM Domain          crm/fcrm/doctype/*        (unmodified)
      ↓
Automation Domain   baton/baton/doctype/*
      ↓
Workflow Engine     baton/workflow/engine.py
      ↓
Agent Runtime       baton/agents/*
      ↓
Channel Adapters    baton/conversation/*
```

Dependencies point downward only. `crm` never imports `baton`.

Read [`docs/AI_CRM_ARCHITECTURE.md`](docs/AI_CRM_ARCHITECTURE.md) first — it maps
what Frappe CRM already provides against what Baton adds, so nothing gets built
twice.

---

## Install

Requires a working Frappe v15 bench with `crm` installed.

```bash
cd frappe-bench

# dependencies
bench get-app https://github.com/shridarpatil/frappe_whatsapp.git
bench --site <site> install-app frappe_whatsapp

# baton
cp -r /path/to/PulpCRM/apps/baton apps/baton
bench --site <site> install-app baton

# schema — all ten phases, in this order
bench --site <site> execute baton.setup.install_all
bench --site <site> execute baton.setup_phase1.install_all
bench --site <site> execute baton.setup_phase3.install_all
bench --site <site> execute baton.setup_phase3b.install_all
bench --site <site> execute baton.setup_phase4.install_all
bench --site <site> execute baton.setup_openwa.install
bench --site <site> execute baton.setup_runtime.install
bench --site <site> execute baton.setup_builder.install_all
bench --site <site> execute baton.setup_agent.install_all
bench --site <site> execute baton.setup_scheduling.install_all
bench --site <site> execute baton.setup_templates.install
bench --site <site> migrate
```

Then apply the CRM frontend changes:

```bash
cd apps/crm
git apply /path/to/PulpCRM/crm-fork/0001-baton-integration.patch
cp -r /path/to/PulpCRM/crm-fork/new-files/frontend/src/* frontend/src/
cd frontend && yarn add @vue-flow/core @vue-flow/background @vue-flow/controls
cd ../../.. && bench build --app crm
```

---

## Configuration

No credentials are stored in this repository. Everything goes in encrypted
Frappe `Password` fields via the UI:

Settings holds **credentials and configuration**. Bots and workflows are *built*
from the sidebar, and pick a configured credential from a list — a builder never
holds a key, and "there isn't one yet" links straight to the page that fixes it.

| Setting | Where |
|---|---|
| LLM provider, model, API key | **Settings → AI → Models & channels** |
| WhatsApp channel, credentials, webhook | **Settings → AI → Models & channels** |
| Conversational agents (used by workflows) | **Settings → AI → Agents** |
| Working hours, holidays, services | **Settings → Scheduling → Working hours** |
| Google sign-in, send-as-me Gmail | **Settings → Google → Sign-in & Gmail** |

| Building | Where |
|---|---|
| Bots and workflows | **Sidebar → AI Automation** (`/crm/automation`) |

### Choosing a WhatsApp channel

| | Meta Cloud API | OpenWA |
|---|---|---|
| Official | yes | no — account-ban risk |
| 24-hour window / templates | enforced | not applicable |
| Sees replies you type on your own phone | **no** | **yes** |
| Setup | business verification | run a container, scan a QR |

That third row decides it for most users. Baton's core promise is that the AI
goes quiet the moment a human steps in. On Meta, a message you send from your
own phone never reaches the API, so handoff detection is partial. OpenWA rides
the real account and sees it, which makes the guarantee complete.

Both are supported; switch between them under Settings → AI → Models & channels.

Baton ships **switched off**. The master switch is at the top of
**Settings → AI → Models & channels**, with per-channel `Auto` / `Draft` / `Off`
underneath it.

Credentials can be **tested while the switch is off** — one throwaway prompt,
reply discarded, nothing reaches a customer. Requiring AI to be on before you
can check whether a key works would mean the only way to find out is to switch
the whole product on and watch.

---

## Safety properties

These are enforced in code and covered by tests:

- **A human always wins.** Any manually-sent WhatsApp message pauses the AI for a
  configurable cooldown and cancels queued follow-ups — including a follow-up
  already scheduled for later.
- **One gate.** Every AI-authored outbound passes `can_ai_send()`. There is no
  second path to sending.
- **Idempotency.** Sends carry unique keys; a worker retry cannot double-message.
- **No AI-authored SQL.** The data chat emits a validated query spec passed to
  `frappe.get_list`, so row-level permissions still apply.
- **Sandboxed conditions.** Workflow expressions run under `frappe.safe_eval`.
- **Verified webhooks.** Inbound WhatsApp requires a valid
  `X-Hub-Signature-256`, and fails closed when no secret is configured.

---

## Licence

The `baton` app is proprietary — © PulpLabs.

⚠️ **Frappe CRM is AGPL-3.0** (its `LICENSE` is the Affero licence; the
`GPL-3.0` string in its `package.json` is a metadata error). §13 covers network
use, and Frappe CRM grants no Application Exception. The contents of
`crm-fork/` are modifications to an AGPL work. Take legal advice before
distributing or hosting commercially — see `docs/AI_CRM_ARCHITECTURE.md` §18.

"Frappe" is a trademark of Frappe Technologies.
