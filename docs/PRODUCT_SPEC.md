# Baton — Product & Build Specification

**by Pulp Labs**
*Lead to cash, one thread.*

Version 1.0 · 18 August 2026
Base platform: [Twenty](https://github.com/twentyhq/twenty) (forked)

---

## 0. How to read this document

This is the single source of truth for what Baton is, why it exists, what has to
be built, and in what order. It exists because the research behind it is spread
across three documents and a long working session, and none of that survives in
anyone's head.

- **Sections 1–3** are the *why*. Read these before arguing about features.
- **Section 4** is the base-platform decision and its consequences. **Section 4.2
  contains a legal issue that must be resolved before Baton is sold to anyone.**
- **Sections 5–7** are the *what* — domain model, functional needs, and the
  non-functional constraints they sit inside.
- **Section 8** is the design system, reproduced in full because the previous
  implementation was deleted and these values were validated, not guessed.
- **Sections 9–11** are the plan, how we know it works, and what is still open.

Supporting research lives in [`research/`](research/):

| File | What it is |
|---|---|
| `vistaar-seam.pdf` | Review of the two prior codebases and their gaps |
| `lead-to-cash-gap.pdf` | Market analysis: the five competitor lanes and the white space |
| `one-deal-two-ways.pdf` | A single deal run twice — today's process vs Baton |

---

## 1. What Baton is

Baton is a **lead-to-cash system for Indian service businesses that invoice by
project** — creative and media agencies, photographers, event and wedding
services, interior and architecture practices, IT and web shops, consultants.
Five to fifty people. Invoices between ₹50,000 and ₹5 lakh.

It runs one unbroken thread:

```
capture from any source → qualify over WhatsApp → native pipeline →
quote → GST invoice → payment link → dunning ladder →
MSME §43B(h) escalation → revenue attributed back to the ad
```

Two things make it different from everything else in the market, and both are
structural rather than cosmetic:

1. **The thread is the unit, not the lead or the invoice.** One record carries a
   relationship from first enquiry to repeat customer. When the collections logic
   messages someone, it can read the sales conversation that preceded it.
2. **The owner never has to leave WhatsApp to run the business.** Decisions arrive
   as cards in the founder's own chat; they reply `1` to send, or record a voice
   note to revise. The web app is for reporting and configuration, not for
   day-to-day operating.

---

## 2. Why — the evidence

### 2.1 The problems, ranked

Ordered by cost to the business against how badly the market serves them.

**1. The owner *is* the system. (Root cause.)**
In a five-to-thirty person Indian business, the founder's personal WhatsApp is
the CRM, the approval queue and the escalation path. Every product in this market
asks them to leave it and operate a dashboard. They don't. This is why SMB CRM
adoption keeps failing, and it is not a training problem — the tool is asking for
a behaviour change that never pays for itself.

**2. Leads leak at the seams, not in the middle.**
Enquiries arrive from WhatsApp, Instagram DMs, Meta ads, Google Forms, IndiaMART,
JustDial, the website, referrals and walk-ins. Perhaps two of those land in a
system. The rest live in someone's notifications until they're buried. The leak
is not bad follow-up — it is that most leads never enter anything to be followed
up *from*.

**3. Speed is the whole game, and everyone is slow.**
Median first response to an inbound B2B lead is around **42 hours**. Replying
within five minutes converts roughly **nine times better**, and the first
responder wins a large majority of deals. **38%** of online leads never get any
reply at all. Almost no SMB measures this, so nobody knows what it costs them.

**4. Follow-up dies at touch two.**
Not because it is hard, but because it is tedious. And when a human *does* step in
manually, the automation doesn't know — so the next scheduled message contradicts
what the founder just promised. Every tool models human takeover as "pause the
bot," which is an admission that the two cannot coexist.

**5. Chasing money is a second, disconnected job.**
Whoever chases payment has none of the sales context — they don't know the client
haggled, or was promised a discount, or always pays a week late.

**6. Founders don't chase, because it feels bad.**
Emotional, not technical, and the real reason collections software sells. Asking
a client for money risks a relationship you need, so the invoice ages until it is
too awkward to raise at all.

**7. Ad spend can't be tied to revenue.**
Cost-per-lead is visible. Cost-per-rupee-collected is not, because the lead and
the payment live in different systems with no shared identity.

**8. The channel itself is a liability.**
Most SMB WhatsApp automation runs on unofficial libraries driving WhatsApp Web.
Numbers get banned at the protocol level, without warning. For a business whose
whole pipeline lives in one number, that is an extinction event.

### 2.2 The regulatory lever — Section 43B(h)

Since **1 April 2024**, under Section 43B(h) of the Income Tax Act, a buyer who
pays a registered micro or small enterprise **later than 45 days** cannot claim
that expense as a deduction in that financial year. Interest accrues at **three
times the RBI bank rate**, compounded, and is itself non-deductible.

This inverts the awkwardness of chasing. An escalation can end not with a threat
but with a fact aimed at the buyer's own accountant. **No competitor in any lane
builds on this.** It is the sharpest India-specific wedge available.

### 2.3 The market — five lanes, none of them the full road

| Lane | Who | Price | Where it stops |
|---|---|---|---|
| WhatsApp engagement | AiSensy, Wati, Interakt, Gallabox, DoubleTick, LeadBuddie | ₹999–5,000/mo | The conversation. No invoice, no GST, no dunning. |
| GST billing | Vyapar, myBillBook, Refrens, Zoho Books, TallyPrime | ₹899/mo–₹3,490/yr | Starts *at* the invoice. A "reminder" is a scheduled template, not a negotiation. |
| AR / collections | Paidnice, Chaser, Upflow, Invoiced, BILL | $69–259/mo | Xero/QuickBooks, email-first, Western. Irrelevant to a business on WhatsApp and UPI. |
| All-in-one agency CRM | GoHighLevel, Keap, Vendasta | $97–497/mo | Built for US agencies, email/SMS-first, steep setup. |
| Collections AI | Credgenics, Skit.ai, CredResolve | Enterprise | Built for lenders with millions of loan accounts. |

**Open-source suites** (Frappe/ERPNext, Odoo, Zoho One) cover more of the journey
than the SaaS point-solutions above — this was a genuine correction to our first
analysis. But none combines a conversational agent, a WhatsApp-native approval
loop and a shared human/AI stream.

### 2.4 The gap

Nobody covers **capture → converse → quote → invoice → collect → attribute** as
one continuous thread about one relationship, for an Indian SMB, operated from
WhatsApp.

---

## 3. Positioning and differentiation

### 3.1 The six bets

Chosen because each is either structurally hard for an incumbent to match, or
something they would have to damage their existing product to add.

**1. The thread is the unit.**
Not the lead, not the invoice. One record, one history, one conversation, from
first enquiry to repeat customer. *Hard to copy because* a WhatsApp platform
bolting on invoicing gets a second table, not a shared history. This must be true
from the first schema.

**2. The owner never has to leave WhatsApp.**
Approval cards in the founder's chat; `1` to send; voice note to revise. The
dashboard reports, it does not operate. *Hard to copy because* incumbents have
spent years making the dashboard the product; telling customers it is now optional
is an admission, not a feature.

**3. Human and AI share one inbox, properly.**
Not "pause the bot" — a colleague. The founder types manually, the AI reads it,
absorbs it, and cancels any queued follow-up the human has made redundant. *Hard
to copy because* it requires the AI's context and the human's messages to be the
same stream; bolt-on chatbots keep them separate by construction.

**4. §43B(h) as a product feature.**
An escalation ladder that ends with a compliance fact aimed at the buyer's
accountant, plus auto-generated MSME Samadhaan filing packs and a "crossing day
45" view. *Hard to copy because* Western AR tools will never build Indian tax law,
and Indian GST tools have no conversation layer to deliver it through.

**5. Speed-to-lead, instrumented and sold.**
Not "we have automation" — *"your median first response is 90 seconds; the
industry median is 42 hours."* On the dashboard, in a monthly email, with revenue
attached. *Hard to copy because* publishing the number requires actually being
fast, which a tool operated through a twice-daily dashboard cannot be.

**6. Real regional language, including voice.**
Collection calls in the debtor's own language, with a hardship override that drops
to a gentle tone and flags a human when someone is genuinely in trouble. *Hard to
copy because* the safety design is the part competitors skip, and it is the part
that stops a screenshot going viral.

### 3.2 What not to build

- **Content generation, image models, Instagram growth.** A different company with
  different buyers and a different sales motion. They will consume the roadmap and
  dilute the pitch.
- **Broadcast price wars.** AiSensy wins the race to ₹999. Compete on what happens
  after the message.
- **Retail and shops.** Vyapar and myBillBook own that segment, and those
  businesses have no lead problem worth solving.

### 3.3 Beachhead and pricing

**Sell to service businesses that invoice by project.** They have exactly the
problem: leads from six channels, long conversational sales cycles, milestone
invoicing, and clients who pay late.

**Positioning line:** *The follow-up system that doesn't leak — from the first
message to money in the bank.*

**Price above the WhatsApp lane, not against it.** They sit at ₹1,500–5,000; Baton
replaces two tools and touches revenue rather than cost, which supports
**₹4,000–12,000/month**. The more interesting option, which nobody offers Indian
SMBs: a base subscription **plus a small percentage of receivables actually
recovered past due**. It aligns with the outcome and is very hard for a per-seat
competitor to answer.

Meter what the market already meters: WhatsApp numbers, seats, AI replies per day,
campaign recipients, voice minutes.

---

## 4. Base platform: Twenty

We fork [twentyhq/twenty](https://github.com/twentyhq/twenty) and tailor it.

### 4.1 Why Twenty

- **Modern, familiar stack.** TypeScript throughout — React front end, NestJS back
  end, GraphQL and REST APIs, PostgreSQL. No PHP, no Rails, no bespoke framework.
- **The fastest-growing open-source CRM** (~45k GitHub stars as of mid-2026), so
  the codebase is actively maintained and the upstream is worth tracking.
- **A genuinely good data model.** Custom objects and fields are first-class, which
  means Baton's Thread, Approval and Invoice objects can be modelled properly
  rather than bolted on.
- **A UI foundation worth keeping.** Record pages, table/kanban views, filters and
  keyboard navigation already exist and are good.

### 4.2 ⚠️ The AGPL problem — resolve before selling

**Twenty is licensed AGPL-3.0.** Unlike GPL-3.0, the AGPL has a *network clause*:
letting users interact with a modified version **over a network counts as
distribution**. Running a modified Twenty as a hosted SaaS therefore obliges us to
release our source, including Baton's differentiators.

Three ways out, and one of them must be chosen before the first paying customer:

1. **Buy a commercial licence from Twenty.** They operate an open-core model; ask
   about commercial/OEM terms. Cleanest path, but it costs money — which sits
   against the zero-recurring-spend constraint.
2. **Open-source Baton too.** Viable if the business is services, hosting and
   support rather than proprietary code. Many Indian SMB tools are sold this way.
3. **Keep the fork internal.** Use Twenty for our own operations only; no external
   users, no obligation. Kills the SaaS plan.

**This is a commercial decision, not a technical one, and it needs a lawyer's eye.
Nothing in this document is legal advice.** It is recorded here because it was
raised, and choosing Twenty means accepting it knowingly.

*Alternative considered:* **Frappe CRM + ERPNext** is GPL-3.0 (no network clause,
so SaaS-safe), Python, and ships Indian GST invoicing, e-invoicing, GSTR reports,
WhatsApp via Meta Cloud API, and already tracks `first_response_time`. It was the
recommendation on licence and India-fit. Twenty was chosen for codebase quality
and stack familiarity. **The consequence: everything Frappe would have given us
for free — GST invoicing, e-invoicing, the WhatsApp channel — is now ours to
build.** Section 6 accounts for this.

### 4.3 What we inherit from Twenty

- Workspaces and multi-tenancy
- Authentication, users, roles and permissions
- A flexible object/field metadata layer
- Record pages, table and kanban views, filtering, sorting, search
- REST and GraphQL APIs
- Timeline and activity logging
- Import/export

### 4.4 What we must build on top

Everything that makes Baton *Baton*, plus what Frappe would have supplied:

- The WhatsApp Cloud API channel (inbound, outbound, templates, 24-hour window)
- The conversational agent and its approval loop
- The unified human/AI message stream
- GST invoicing, e-invoicing, invoice numbering, payment links
- The dunning ladder and §43B(h) escalation
- Speed-to-lead instrumentation
- Multi-source capture (Meta Lead Ads, Google Forms, Instagram, referral, cold)
- Revenue attribution back to ad spend
- The Baton design system (Section 8)

---

## 5. Domain model

Expressed as Twenty custom objects where possible, native tables where not.

### 5.1 The spine

**`Thread`** — one per contact per workspace, **never closed**.
Fields: `contact_id`, `channel`, `service_window_expires_at`, `ai_enabled`,
`handover_state`, `rolling_summary`, `ai_turn_count`, `needs_attention`,
`last_inbound_at`, `last_outbound_at`.

A repeat customer opens a *second opportunity on the same thread*. This is the
property competitors cannot retrofit.

**`Message`** — belongs to a Thread.
Fields: `thread_id`, **`author` (`contact` | `human` | `ai`)**, `author_user_id`,
`body`, `media_url`, `wa_message_id`, `direction`, `is_template`,
`template_name`, `intent`, `sentiment`, `delivered_at`, `read_at`, `created_at`.

`author` is three words of schema and it is the entire differentiator. Human and
AI messages are rows in **one table** distinguished by a column, not two systems
reconciled afterwards.

### 5.2 Around the spine

| Object | Purpose | Key fields |
|---|---|---|
| `Contact` | A person | `phone_normalised` (**unique index per workspace**), `email`, `name`, `source`, `source_detail` |
| `Company` | An organisation | `name`, `gstin`, `address`, `is_msme` |
| `Opportunity` | A deal on a Thread | `thread_id`, `stage`, `value`, `expected_close`, `quiet_since` |
| `Approval` | A decision the agent needs | `code` (e.g. `A7`), `kind`, `payload`, `draft_text`, `status`, `resolved_by`, `costs_template` |
| `Quote` | Pre-invoice | `opportunity_id`, `line_items`, `valid_until`, `pdf_url` |
| `Invoice` | GST invoice | `opportunity_id`, `number`, `gst_breakdown`, `due_date`, `status`, `age_days` |
| `Payment` | Money received | `invoice_id`, `amount`, `method`, `gateway_ref`, `reconciled_at` |
| `TemplateDefinition` | Meta template registry | `name`, `category`, `language`, `components`, `meta_status` |
| `Activity` | Append-only timeline | `subject_type`, `subject_id`, `verb`, `actor`, `meta` |
| `AdAttribution` | Ad → revenue | `ad_id`, `form_id`, `campaign`, `spend`, `leads`, `collected` |

**The chain that matters:** `Invoice → Opportunity → Thread`. The collections
logic can read the sales conversation. That is the product thesis expressed as
foreign keys.

### 5.3 Deliberate modelling decisions

- **No separate `Lead` object.** Salesforce's Lead→Opportunity conversion is
  exactly what loses history, and rebuilding it would import the problem we sell
  against. A Contact has a Thread from first touch; an Opportunity opens on it
  when there is a real deal.
- **`phone_normalised` is indexed and unique per workspace.** The prior codebase
  loaded every client into memory and normalised in Python on every inbound
  message. At a thousand contacts that is slow; at scale it falls over.
- **Money is stored in paise, always.** Rupees are a presentation concern. A prior
  bug shipped payment links short by a paisa because `int(1.15 * 100)` is `114`.

---

## 6. Functional requirements — the needs

### 6.1 Capture — every source, one endpoint

- **Meta Lead Ads** webhook, with signature verification and Graph API fetch
- **Google Forms** via a generic intake webhook
- **Inbound WhatsApp** to the business number
- **Instagram DMs**
- **Referral** and **cold reply**, tagged as such
- **Manual entry** and CSV import
- A single generic `POST /intake` so a new source is configuration, not code

Every captured lead carries `source` and `source_detail` (the ad or form id) from
the first moment, because attribution (§6.8) depends on it surviving to the
payment.

**Acceptance:** a form submission at 9pm produces a real WhatsApp reply in under
sixty seconds, with the ad id attached to the record.

### 6.2 The WhatsApp layer — Meta Cloud API, direct

We register our own Meta app. **No BSP reseller**, so there is no platform
subscription.

**The economics are a design constraint, not a footnote.** Inbound messages and
every reply inside the **24-hour customer service window** are free.
Business-initiated **template** messages are billed per message (~₹0.35 utility,
~₹0.9 marketing in India, volume-discounted). Therefore:

> **Baton is architected to stay inside the 24-hour window and to treat templates
> as a scarce, budgeted resource.**

Requirements:

- `GET /webhooks/whatsapp` — `hub.challenge` verification
- `POST /webhooks/whatsapp` — `X-Hub-Signature-256` HMAC **verified before parsing**
- Webhook handler does nothing but normalise, persist and enqueue; it returns 200 fast
- **The 24-hour window is a modelled field**, not a comment. Every inbound message
  sets `service_window_expires_at = now + 24h`. The dispatcher branches on it:
  in-window → free-form, free; out-of-window → an approved template is *required*,
  which costs, so it goes through a budget check and is recorded.
- **Template registry** synced from the Graph API with category, language,
  components and Meta's approval state. The prior codebase had no representation
  of templates at all — that gap, not the transport, is the real cost of Cloud API.
- **Outbox** with a retryable-vs-permanent split: a provider blip is retried, a
  rejected template is dead-lettered, nothing is silently lost
- **Media handling** — inbound images stored and flagged. A UPI screenshot with no
  caption is the single most common reply to a payment reminder in India, and the
  prior system threw those away entirely.
- **Port boundary:** `MessagingPort.send(thread, content) → SendResult`, so a
  second transport is a file, not a refactor

**A consequence that changes one interaction.** A number on the Cloud API cannot
also be used in the WhatsApp app. So the founder cannot type into the customer's
thread from their own phone. Instead:

- **The business number** runs on Cloud API and carries customer conversations.
  Manual replies go through Baton's inbox and land in the same `messages` table,
  so the one-stream property survives — only the typing surface moves.
- **Approval cards** go to the founder's *personal* WhatsApp as a separate thread,
  costing one utility template per card. Their `1`/`2`/`3` reply comes back inside
  the window, free, as does everything else for the next day.

### 6.3 The agent

**An explicit state machine in pure code, with the LLM called only for extraction
and drafting.** Rejecting a graph framework deliberately:

- Policy — what to do next given thread state — is only testable without a model
  if it is pure
- Fewer LLM calls per turn matters directly against a free-tier rate limit
- One agent following one ladder does not need multi-agent branching

Responsibilities:

- **Qualify** — one question at a time, from a per-category required-fields list.
  Never quotes a price; prices come only from the rate card.
- **Extract** — structured facts from free text and voice notes: intent, promised
  date, delay reason, sentiment, budget signals
- **Draft** — a reply in the business's voice, with the thread's history and the
  invoice facts in context
- **Summarise** — a rolling thread summary written on message receipt, not
  regenerated on page load (slow, costly, and different every refresh)

**Guardrails — a validator, not a prompt.** The agent may ask why, empathise,
restate the amount owed, re-send a link, propose a part payment, note an offered
date, and hand over. It must **never** agree a discount, agree a different amount,
waive anything, accept or deny a dispute, threaten legal action, or make claims
about goods delivered. A generated draft is checked against these rules *before*
sending; a draft that fails is flagged, never silently dropped.

**Hardship override.** If a message shows real distress — illness, bereavement,
business failure — the agent drops to the gentlest tone, sends one short human
reply, stops, and flags the thread. Firm tone is never applied to such a message.

**Honesty.** If asked directly whether it is a bot, the agent does not deny it.

**Turn caps.** No more than six AI turns on one thread without a human looking;
never two replies in a row; only inside working hours except a first
acknowledgement; stop permanently on handover, payment or cancellation.

### 6.4 Approvals — the signature interaction

- The agent stops before anything irreversible and writes an `Approval` row
- A card is dispatched to the founder's WhatsApp **and** appears in the web queue —
  the same row, resolvable from either
- Card shows a short code (`A7`) so a specific card can be answered when several
  are pending
- **The draft is quoted verbatim, never paraphrased.** Approving a message means
  seeing the exact words that will be sent.
- `1` sends · `2` plus instructions (typed or voice) revises and re-asks · `3` skips
- Where sending would fall outside the 24-hour window, the card says so and names
  the template that will be billed
- **A human's manual message re-enters the state machine the same way an approval
  does** — it is just a `Message` with `author=human`, which recomputes state and
  **cancels any queued follow-up the human has made redundant**

**Acceptance:** an integration test in which a `human` message lands mid-sequence
and asserts the queued AI follow-up is cancelled. *If this test does not exist,
the feature is not built.*

### 6.5 Pipeline

- Tenant-configurable stages, ordered
- Kanban and table views (largely inherited from Twenty)
- Per-stage value roll-up and weighted pipeline value
- "Quiet for N days" surfaced on the card — the most actionable signal there is
- Lead scoring as **transparent heuristics with a stated basis**, not a fabricated
  ML number. Field completeness, engagement, stage weight. Every figure carries a
  `basis` string so the UI can explain *why*.

### 6.6 Money

Must be built; Twenty has none of this.

- **GST invoices** — CGST/SGST/IGST split by place of supply, HSN/SAC codes,
  invoice numbering with a per-workspace series and a race-safe sequence
- **E-invoicing / IRN** where the turnover threshold applies, with the QR code
- **Quotes** that convert to invoices without re-entry
- **Payment links** (Razorpay first) embedded in the invoice PDF and the WhatsApp
  message, plus a UPI QR
- **Webhook reconciliation** with signature verification, **and** a polling
  reconciler for payments whose webhook was lost — this happened in production
  before and the invoice silently stayed unpaid
- **Partial payments** with proper allocation; a short payment must be visible
  immediately, not three weeks later
- **Recurring invoices** for retainers
- Per-workspace payment credentials, encrypted, so money settles into the
  customer's own account

### 6.7 Collections and §43B(h)

- **Staged dunning ladder** anchored to the due date, with working hours, quiet
  hours and a daily cap
- **Promise tracking** — a promised date pauses the ladder and sets its own check
- **Tone settings**: Warm / Neutral / Firm, per workspace with a per-client
  override. "Firm" means short sentences, a clear deadline, no softening — never
  insults, threats, or untrue implications.
- **The §43B(h) ladder step.** A "crossing day 45" view; a drafted notice stating
  that the supplier is a registered micro/small enterprise, that payment beyond 45
  days makes the expense non-deductible for the buyer this financial year, and
  that interest accrues at three times the RBI bank rate; auto-generated **MSME
  Samadhaan** filing packs.
- Escalation to a human at any sign of dispute, hardship or a discount request

### 6.8 Attribution

- `source` and `source_detail` captured at intake and carried through
  Opportunity → Invoice → Payment
- Dashboard: **cost per rupee collected**, per ad, per campaign, per channel
- Monthly digest email with the figure

**Acceptance:** "this ad produced ₹X collected against ₹Y spent" is a query, not a
spreadsheet exercise.

### 6.9 Admin and settings

- WhatsApp: business number, Cloud API credentials, template registry and status
- Business profile: name, GSTIN, address, bank details, invoice series, logo
- Rate card / service catalogue — the only source of prices the agent may quote
- Team, roles and permissions — **wired to real checks on day one.** A prior
  codebase defined five roles and twenty-eight permissions and never called the
  check once; every route collapsed to admin-or-not. A permission model with zero
  call sites is worse than none, because it reads as protection that isn't there.
- Tone and automation settings, per workspace and per client

---

## 7. Non-functional requirements

### 7.1 Zero recurring spend

A hard filter on every technology choice. Self-hosted OSS or free tier only.

| Need | Choice | What breaks first |
|---|---|---|
| Database | PostgreSQL (Twenty's own), Neon free tier hosted | 0.5 GB, autosuspend cold starts |
| Queue / cache | Redis, self-hosted alongside the API | memory on a small box |
| Front end hosting | Vercel Hobby **(non-commercial only — must change before first paying customer)** | licence terms, not capacity |
| API + workers | Render / Koyeb free tier | **spins down when idle** |
| Webhook receiver | **Cloudflare Worker** (free, always on) | 100k req/day |
| LLM | Groq free tier, Gemini Flash free tier | requests/min, tokens/day |
| Embeddings | sentence-transformers, local | CPU |
| Voice → text | faster-whisper, local | CPU |
| Object storage | Cloudflare R2 free | 10 GB |
| Error tracking | GlitchTip, self-hosted | you run it |
| CI | GitHub Actions | 2,000 min/mo private |
| Dev webhooks | Cloudflare Tunnel | — |

**The weak link, stated plainly:** a free backend host that spins down **will drop
Meta webhooks**. The mitigation is also good design — a Cloudflare Worker receives
the webhook (always on, free), verifies the signature, and pushes to a queue the
backend drains when it wakes.

**Voice calling is out of v1.** There is no free telephony. The domain model must
not preclude it.

### 7.2 Multi-tenancy

Twenty provides workspaces. Every Baton object added must be workspace-scoped and
**tested for isolation**, not assumed. Build a dedicated isolation suite that
creates two workspaces and asserts every Baton table is unreadable across the
boundary, iterating a single `TENANT_TABLES` constant so a new table cannot be
forgotten.

*Why this is emphasised:* in a prior codebase, **118 of 120 queries had no
organisation filter**, relying entirely on Postgres row-level security — which had
already failed once, because the hosting provider's default role carried
`BYPASSRLS`.

### 7.3 Security

- Short-lived access tokens plus refresh in an httpOnly cookie. Not 24-hour tokens
  in `localStorage`, and never a JWT in an SSE query string where it lands in proxy logs.
- All provider credentials encrypted at rest with a rotating key set
- Webhook signatures verified before parsing, on every inbound webhook
- Rate limiting that does not trust `X-Forwarded-For` verbatim
- No credentials in the repo. **See the warning in Section 12.**

### 7.4 Observability

- Structured logs with a correlation id per request, traceable across modules
- `/health` reporting outbox depth — a pending count that climbs means nothing is
  sending while every other check stays green
- Metrics on: first-response time, template spend, approval latency, dunning
  outcomes, webhook failures

---

## 8. The design system

Reproduced in full because the prior implementation was deleted and these values
were **validated, not guessed** — every text pair below passes WCAG AA at 4.5:1 in
both themes, verified programmatically.

### 8.1 Colour — three layers

Ordered by importance to the reader. **The brand is deliberately the quietest**,
because in an ops tool the state *is* the content.

**Primary — tangerine.** Warm and unusual for B2B, which is the point. It owns
interaction: buttons, active nav, focus rings.

```
--color-tang-50   oklch(0.972 0.018 62)
--color-tang-100  oklch(0.945 0.040 60)
--color-tang-200  oklch(0.898 0.075 58)
--color-tang-300  oklch(0.845 0.112 55)
--color-tang-400  oklch(0.788 0.148 53)
--color-tang-500  oklch(0.720 0.175 52)   ← the brand
--color-tang-600  oklch(0.640 0.166 48)
--color-tang-700  oklch(0.545 0.146 45)
--color-tang-800  oklch(0.450 0.118 42)
--color-tang-900  oklch(0.360 0.090 40)
--color-tang-950  oklch(0.258 0.062 38)
```

**Tangerine is too light to carry white text.** Hence three brand tokens:

| Token | Light | Dark | Job |
|---|---|---|---|
| `--brand` | `tang-500` | `tang-500` | the vivid fill |
| `--fg-onbrand` | `oklch(0.205 0.030 50)` | `oklch(0.170 0.022 50)` | **dark** text on that fill |
| `--brand-ink` | `tang-700` | `tang-400` | brand-coloured *text* and icons |
| `--brand-tint` | `tang-50` | 15% tang-500 over surface | washes, active rows |

**Secondary — teal**, tangerine's complement:

```
--color-teal-100  oklch(0.950 0.022 205)
--color-teal-300  oklch(0.822 0.075 205)
--color-teal-400  oklch(0.740 0.098 204)   ← dark-mode accent
--color-teal-500  oklch(0.640 0.108 205)
--color-teal-600  oklch(0.520 0.100 207)   ← light-mode accent
--color-teal-700  oklch(0.430 0.086 209)
```

**Neutrals — warm bias**, so the greys belong beside tangerine rather than
fighting it. Hue 50–70, chroma ≤ 0.012:

```
ink-0    oklch(1 0 0)              ink-500   oklch(0.558 0.012 62)
ink-50   oklch(0.986 0.003 70)     ink-600   oklch(0.448 0.012 60)
ink-100  oklch(0.968 0.005 70)     ink-700   oklch(0.372 0.011 58)
ink-200  oklch(0.930 0.007 68)     ink-800   oklch(0.276 0.010 56)
ink-300  oklch(0.872 0.009 66)     ink-900   oklch(0.212 0.008 54)
ink-400  oklch(0.712 0.011 64)     ink-950   oklch(0.156 0.007 52)
                                   ink-1000  oklch(0.112 0.006 50)
```

**Semantic state — deliberately outside the tangerine hue band.** Because the
brand occupies hues 40–60, the state hues were *moved out of it*. A status sharing
a hue with the primary button is a status nobody can read at a glance.

| Token | Meaning | Light | Dark |
|---|---|---|---|
| `--waiting` | needs a human | `oklch(0.500 0.190 300)` violet | `oklch(0.790 0.140 300)` |
| `--overdue` | past due / failed | `oklch(0.530 0.210 12)` crimson | `oklch(0.730 0.165 15)` |
| `--won` | closed / paid | `oklch(0.500 0.140 158)` emerald | `oklch(0.760 0.150 160)` |
| `--cold` | dormant | `ink-600` | `ink-400` |
| **`--ai`** | **generated by Baton** | `oklch(0.520 0.100 207)` | `oklch(0.790 0.105 202)` |

**`--ai` is a product requirement, not decoration.** Human and AI messages share
one stream, so the reader must tell them apart at a glance without reading a
label. It takes the secondary teal — Baton's own voice, in the brand's complement.

Tints are `color-mix(in oklab, <state> 9–11%, var(--surface))`.

**Pipeline stages get a *sequential* ramp**, not categorical colours, because
stages are ordered — varying chroma along the brand hue:

```
--stage-1  oklch(0.790 0.030 56)   → --stage-5  = --color-tang-500
```

**Surfaces.** Light: `bg` ink-50, `surface` ink-0, `sunk` ink-100.
Dark: `bg` ink-1000, `surface` ink-950, `sunk` oklch(0.132 0.006 52),
`raised` ink-900.

### 8.2 Typography

Self-hosted, no CDN, no layout shift.

- **Bricolage Grotesque** (OFL) — wordmark, marketing surface, login. Real
  character, confined to where personality helps.
- **Geist Sans** (OFL) — all product UI. Boring on purpose; an ops tool read for
  eight hours a day should not have an opinion.
- **Geist Mono** (OFL) — every rupee figure, invoice number, GSTIN, phone number,
  timestamp and id, with `font-variant-numeric: tabular-nums`.

Deliberately **not Inter** — it is the default that signals no decision was made.

**Money always renders through one component** using `Intl.NumberFormat("en-IN")`,
so amounts read in the Indian grouping the customer expects: **₹5,66,400**, not
₹566,400.

### 8.3 Density, radius, elevation

- **Two density modes, Comfortable and Compact, as token-level switches**
  (`--row-py`, `--row-px`, `--control-h`, `--text-body`, `--text-meta`). A CRM at
  ten thousand leads is unusable at consumer spacing, and this **cannot be
  retrofitted** once components hardcode their own padding.
- Radius scale: `4 / 6 / 8 (base) / 12 / 16 / 22`. Not `rounded-lg` on everything.
- **Light mode lifts with a shadow ramp. Dark mode lifts with surface lightness
  steps plus a hairline inset ring** — shadows do not read on a dark ground, and
  pretending otherwise is why most dark modes look flat.

### 8.4 Motion

On-brand — a baton is a handoff — but restrained.

- Easing `cubic-bezier(0.22, 1, 0.36, 1)`; durations 130 / 220 / 380ms
- Shared-element transitions when a record moves between stages
- Approval cards animate out on decision, so the queue visibly drains
- Staggered list entrances (~50ms apart) so a list reads as a list, not a flash
- **Lottie**, authored locally rather than fetched from a CDN — no network, no
  cost, works offline:
  - `all-clear` — the approvals queue reaching zero, the one genuinely good moment
    in a day spent chasing money
  - `listening` — Baton actively working a thread
- **Everything behind `prefers-reduced-motion`.** Where an animation carries
  meaning, it is *replaced* with a static icon, not removed — removing it would
  remove the message.

### 8.5 Rules that are easy to break and expensive to fix

1. **Define every colour on bare `:root` first.** A colour whose only definition
   sits inside `@media (prefers-color-scheme: dark)` never applies to the viewer
   who has made no explicit choice — which is most of them. Cover all three states:
   bare `:root`, the media query guarded against an explicit light choice, and the
   `[data-theme="dark"]` stamp.
2. **Tailwind v4 emits only theme variables it sees used by a utility class.**
   Anything reached through `var()` silently resolves to nothing — a ramp that
   renders *invisible* rather than wrong, which is the worst way to find out. Use
   `@theme static`.
3. **Tailwind v4's Preflight dropped `cursor: pointer` on buttons.** Restore it in
   the base layer or every button in the app has an arrow cursor.
4. **Density is a token, not a prop.**
5. **Contrast is measured, not eyeballed.** Ship a checker that converts the OKLCH
   tokens to sRGB, audits every text pair in both themes at 4.5:1, and **exits
   non-zero** so it can gate CI. The first run of this found six failing pairs —
   including all four status pills, the layer that carries the actual information.
6. **Nothing ships to a product screen before it exists on the style guide**, with
   every state, in both themes.
7. **Screenshot with real time.** `--virtual-time-budget` fast-forwards timers but
   not `requestAnimationFrame`, so motion-driven content freezes at `opacity: 0`
   and looks broken when it isn't. Use CDP with a real wait.
8. **Measure responsive breakage, don't eyeball it.** Assert
   `document.documentElement.scrollWidth <= clientWidth` at 375px on every route.
   Wide content scrolls inside its own container; the page body never does.

---

## 9. Build phases

Each phase ends in something demonstrable. Phase 0 gates everything.

| # | Phase | Demo at the end |
|---|---|---|
| **0** | **Licence decision (§4.2)** + fork, build, run Twenty locally | `yarn start` green; the AGPL path chosen in writing |
| 1 | Baton design system layered onto Twenty's UI: tokens, both themes, density, style guide route | Every component and state, light and dark, on one page |
| 2 | Domain objects — Thread, Message, Approval, and the workspace isolation suite | A test that fails loudly on a cross-workspace read |
| 3 | WhatsApp spine — Cloud API webhooks, signature verification, 24-hour window, template registry, outbox | Message the business number; it appears in Baton; reply from the inbox |
| 4 | **Human + AI, one stream** — drafting, approval cards, `1` to send | Type manually; watch the queued follow-up cancel itself |
| 5 | Capture + pipeline — multi-source intake, stages, qualification | Submit a form; a real reply lands in under a minute |
| 6 | Money — GST invoicing, payment links, reconciliation | Approve → invoice → pay → chasing stops |
| 7 | Collections + §43B(h) — ladder, tone, promise tracking, escalation | A 46-day invoice moves after the notice |
| 8 | Attribution — ad id carried end to end | "This ad produced ₹X collected" |
| 9 | Voice — regional-language collection calls with hardship override | *Post-v1; needs paid telephony* |

**V1 scope is lead-side deep, money-side thin:** phases 0–5 in full, phase 6 to a
working minimum, phases 7–9 after.

---

## 10. Verification

**Per phase:** the demo above must pass by hand, plus:

- **Domain logic in pure unit tests** — the window policy, the dunning ladder, GST
  splitting and the state machine must all be exercisable with no model and no
  network
- **Workspace isolation suite**, run in CI against ephemeral Postgres
- **WhatsApp:** signature verification against real Meta payload fixtures; window
  expiry and template-required branching against a fake clock; the outbox's
  retryable/permanent split with an injected failing adapter
- **The differentiator, explicitly:** the human-message-cancels-queued-follow-up
  test from §6.4
- **Front end:** `tsc --noEmit`, ESLint actually configured and running, Playwright
  over login → inbox → approve → send
- **Both themes plus system default** checked on the style guide
- **Contrast checker** and the **375px scrollWidth assertion** in CI

**End-to-end acceptance for v1** is the worked example run for real: a form
submission at 9pm produces a WhatsApp reply in under a minute, an approval card on
the founder's phone, and a lead in the pipeline with its source attributed — with
the founder never opening a dashboard to make it happen.

---

## 11. Open decisions

1. **The AGPL path (§4.2).** Commercial licence, open-source Baton, or internal
   use only. **Blocks selling. Decide first.**
2. **Vercel Hobby is non-commercial.** Fine while building; must change before the
   first paying customer.
3. **Who signs the messages** — a real staff name, the company name, or an invented
   first name? Biggest single factor in whether replies read as human, and a made-up
   name is a mild version of the bot-honesty question.
4. **Turn cap.** Six AI turns before it stops and asks for a human — higher means
   more autonomy and more loop risk.
5. **Languages.** English only for v1, or Hindi and Kannada too? "Firm" does not
   translate the same way, so the persona work multiplies.
6. **Payment screenshots.** Store and flag (small), or read with a vision model and
   auto-match against the invoice (much bigger, genuinely useful, probably its own
   project)?
7. **Tone names.** Warm / Neutral / Firm as specified, or the literal
   polite / professional / aggressive that was originally asked for.

---

## 12. Appendix

### 12.1 Reference material

- **`research/`** — the three PDFs listed in §0
- **`vistaar-agent/`** — prior lead agent. Worth reading for: the WhatsApp-native
  approval card loop, the nurture sweep, and the LangGraph qualify→approve→propose
  flow. Contains the bug Baton must design out: inbound handling drops every
  `from_me` message, so the founder's manual replies are invisible to the agent.
- **`vistaar-payment-bot - Copy/`** — prior payment bot. Worth reading for: the
  four-layer tenant isolation, encrypted per-tenant credential resolution, the
  outbox with its retryable/permanent split, and `docs/plan-conversational-whatsapp.md`,
  which is the best existing thinking on tone, guardrails and the hardship override.

### 12.2 ⚠️ Credentials

Live credentials were shared in plain text during this project — a **live**
Razorpay key and secret, plus API keys and account passwords for voice, messaging
and database providers. **Treat all of them as disclosed and rotate them**,
starting with the Razorpay live secret, because that one moves money.

`docs/MVP_READY.md` in the payment-bot repo also records that the Supabase
database password was committed in plaintext and should be treated as
compromised; as of that document it had not been reset. Both prior repos keep
`.env` files inside the project folders.

**No credential belongs in this repository.**
