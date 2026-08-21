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
| **OpenWA connector** — self-hosted WhatsApp bridge, HMAC-verified | ✅ live-tested |
| **Connections UI** — pick Meta or OpenWA, configure and test in the CRM | ✅ |
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
| WhatsApp channel, credentials, webhook | **Connections** page in the CRM (`/crm/connections`) |

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

Both are supported; switch between them on the Connections page.

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
