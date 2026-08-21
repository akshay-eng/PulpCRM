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
| Visual workflow builder in the CRM UI (`/crm/workflows`, Vue Flow) | ✅ |
| Multi-provider LLM — OpenAI-compatible, Anthropic, Gemini, Ollama, Azure | ✅ tested |
| AI qualification — configurable criteria, weights, score bands | ✅ tested |
| Lead → Deal conversion, assignment, owner notification | ✅ tested |
| Human handoff state machine with cooldown and resume policy | ✅ tested |
| Natural-language data chat (permission-safe, never SQL) | ✅ tested |
| Follow-up ladder, generated as an editable workflow | ✅ |
| WhatsApp webhook signature verification (fixes an upstream hole) | ✅ tested |
| Meta Lead Ads ingestion | ⏳ native to Frappe CRM; hardening pending |
| Deal monitoring, escalation, MCP, agent builder, dashboard | ⏳ not started |

**64 tests**: `bench --site <site> run-tests --app baton`

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

# schema
bench --site <site> execute baton.setup.install_all
bench --site <site> execute baton.setup_phase1.install_all
bench --site <site> execute baton.setup_phase3.install_all
bench --site <site> execute baton.setup_phase3b.install_all
bench --site <site> execute baton.setup_phase4.install_all
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

| Setting | Where |
|---|---|
| LLM provider, model, API key | `Baton AI Model` |
| Meta App Secret (webhook verification) | `Baton Settings → Meta` |
| WhatsApp token, phone ID, WABA ID | `WhatsApp Account` |

Baton ships **switched off**. `Baton Settings → ai_enabled` is the global kill
switch, with per-channel `Auto` / `Draft` / `Off` on top.

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
