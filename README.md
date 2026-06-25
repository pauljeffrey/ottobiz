# Ottobiz

**Ottobiz** is an AI-powered business automation platform that simulates and orchestrates the full commercial lifecycle—from product discovery and payment verification through multi-party logistics coordination, inventory updates, and post-purchase support. A FastAPI backend coordinates specialized LLM agents over Redis session state and PostgreSQL; a Next.js demo frontend exposes three live chat panes (customer, business, logistics) with real-time transparency into catalog, orders, and agent processes.

---

## GitHub description (short)

> Multi-agent AI platform for SMB commerce: customer sales, vendor ops, logistics coordination, Paystack payments, inventory, and a live three-pane demo UI with session transparency.

---

## Table of contents

- [Why Ottobiz](#why-ottobiz)
- [Decision & idea choices](#decision--idea-choices)
- [Architectural choices](#architectural-choices)
- [Multi-agent orchestration](#multi-agent-orchestration)
- [Engineering bottlenecks](#engineering-bottlenecks)
- [Trade-offs](#trade-offs)
- [Evaluation](#evaluation)
- [Edge cases](#edge-cases)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Getting started](#getting-started)
- [Deployment](#deployment)
- [Documentation](#documentation)

---

## Why Ottobiz

Small and medium businesses often run sales, fulfillment, and support across WhatsApp, bank transfers, spreadsheets, and ad-hoc courier arrangements. Ottobiz explores how **specialized AI agents**—not a single monolithic chatbot—can automate that workflow while keeping humans in the loop for vendor and logistics decisions.

The demo frontend is deliberately **transparent**: operators can watch catalog refreshes, active orders, discussed products, and inventory activity while three agents converse, making the system auditable during development and stakeholder demos.

---

## Decision & idea choices

| Choice | Rationale |
|--------|-----------|
| **Multi-agent over one mega-prompt** | Sales, payment proof, complaints, upselling, and logistics have different guardrails and tools. Splitting agents reduces prompt bloat and makes failures easier to isolate. |
| **Central agent as coordination hub** | Customer-facing specialists handle intent; a **Central Agent** owns cross-party routing (customer ↔ vendor ↔ logistics), order creation after payment gates, and structured process updates. |
| **Redis for session, Postgres for records** | Chat turns, product caches, open **processes**, and inbox queues need low-latency read/write. Orders, catalog rows, Paystack events, and chat summaries belong in durable storage. |
| **Process-centric journeys** | Each enquiry or purchase is tracked as a `process_id` with `task_type`, product name, order linkage, and completion state—so multi-turn flows do not collapse into undifferentiated chat history. |
| **Inbox queues between parties** | Vendor and logistics UIs poll `inbox:{party_id}` instead of sharing one chat thread, mirroring how real businesses use separate channels. |
| **Pydantic AI (from LangChain-era design)** | Structured tool calls, typed dependencies, and provider-agnostic models (OpenAI, Gemini, Anthropic) with Logfire instrumentation for observability. |
| **Demo-first frontend** | Three chat panes + live side panels validate backend behavior without requiring WhatsApp or production traffic. Currency conversion runs client-side for international demos. |
| **Tiered product vision (Free / Gold / Platinum)** | Feature flags (logistics, upselling, analytics) map to commercial tiers; `DEBUG=true` bypasses restrictions during development. |
| **Paystack per-vendor keys** | Each business stores its own Paystack credentials; webhooks and verification tie charges back to `{user_id}:{vendor_id}` Redis state. |

---

## Architectural choices

### High-level system

```mermaid
flowchart TB
  subgraph clients [Clients]
    FE[Next.js demo UI]
    WA[WhatsApp webhook]
  end

  subgraph api [FastAPI]
    CUST[/customer/chat]
    BIZ[/business/chat]
    LOG[/logistics/chat]
    SESS[/session/* transparency APIs]
  end

  subgraph agents [Agent layer]
    CONV[Conversational agent]
    SPEC[Specialists: product, payment, logistics, complaint, upsell, marketing]
    CENT[Central agent]
    BCHAT[Business chat agent]
  end

  subgraph data [Data layer]
    REDIS[(Redis session + inbox)]
    PG[(PostgreSQL)]
  end

  FE --> api
  WA --> api
  CUST --> CONV
  CONV --> SPEC
  SPEC --> CENT
  BIZ --> BCHAT
  BCHAT --> CENT
  LOG --> BCHAT
  CONV --> REDIS
  CENT --> REDIS
  CENT --> PG
  SPEC --> PG
  SESS --> REDIS
  SESS --> PG
```

### Session keys (Redis)

| Key pattern | Purpose |
|-------------|---------|
| `{user_id}:{vendor_id}` | Full customer session: chat history, products cache, processes, uploads |
| `{vendor_id}` or `{logistic_id}` | Business/logistics party chat and coordination context |
| `inbox:{recipient_id}` | Pending messages for polling UIs |
| `paystack_ref:{reference}` | Short-lived checkout correlation for webhooks |

### Backend layout

- **`app/main.py`** — FastAPI app, CORS, lifecycle (DB init, seed), router registration.
- **`app/backend/chatbot/agents/`** — Specialist and central agents built on `BaseAgent`.
- **`app/backend/chatbot/interface/`** — Customer and business chat entrypoints (orchestration, summarization, file handling).
- **`app/backend/api/routers/`** — REST APIs for chat, session transparency, analytics, inventory, supply chain, payments.
- **`app/backend/db/`** — SQL migrations, schemas, cache utilities, population scripts.

### Frontend layout

- **`frontend/app/page.tsx`** — Single-page workspace: persona selectors, three chat panes, transparency panels, Reports tab, How to Use guide.
- **`frontend/lib/use-transparency-panels.ts`** — Polling hooks for catalog, orders, agent context, inventory activity.
- **`frontend/lib/currency.ts`** — Client-side FX display for demo audiences (NGN, USD, CAD, AUD, GBP, EUR, ZAR).
- **`frontend/lib/api-base.ts`** — Resolves `NEXT_PUBLIC_BACKEND_URL` or same-origin `/backend` proxy.

### Deployment topology

| Component | Typical target |
|-----------|----------------|
| Backend + Postgres + Redis | Dokploy / Docker Compose on VPS |
| Frontend | Vercel (Root Directory: `frontend/`) |
| Object storage (receipts/media) | Cloudflare R2 (optional) |
| Observability | Logfire (optional) |

Detailed backend flow: [`app/backend/readme/architectural_workflow.md`](app/backend/readme/architectural_workflow.md).

---

## Multi-agent orchestration

Ottobiz uses a **hub-and-spoke** pattern: customer-facing orchestration delegates to specialists; specialists escalate to the **Central Agent** when multiple parties must act.

### Customer channel

1. **POST `/api/v1/customer/chat`** → `user_chat_interface.chat()`
2. Load `{user_id}:{vendor_id}` from Redis; optionally process uploads (receipts, images).
3. Summarize chat history when word limits are exceeded; persist summaries to Postgres.
4. **`run_conversational_agent`** — primary store associate; chooses tools that invoke:
   - **Product agent** — catalog search, payment links, vendor notify
   - **Payment verification agent** — receipt / reference checks → `notify_central_payment_confirmed`
   - **Logistics agent** — delivery context → central handoff
   - **Customer complaint agent** — de-escalation and escalation
   - **Upselling / ads-marketing agents** — alternates and post-purchase suggestions

### Central agent loop

The Central Agent implements a **three-step execution loop** (audit → tool execution → strategic routing):

1. **Status audit** — Read `finished_tasks`, process history, payment state.
2. **Tool execution** — `create_order`, `mutate_vendor_catalog`, `update_process`, Paystack-aware payment checks, logistics context.
3. **Strategic routing** — Emit structured output: `recipient`, `message`, `next_step`, `reasoning`.

**Hard guardrails** (enforced in prompts and tools):

- No order creation or logistics dispatch until payment is verified.
- Vendor catalog mutations only after explicit vendor authorization.
- Customer-facing copy is **polished** (short, chat-native) before delivery.
- Processes marked **completed** when delivery objectives are met.

### Business & logistics channel

1. **POST `/api/v1/business/chat`** or **`/api/v1/logistics/chat`**
2. **`business_chat_agent`** operates in two modes:
   - **Mode 1 — Direct ops:** analytics, inventory reads, `mutate_vendor_catalog` for the vendor’s own store.
   - **Mode 2 — Coordination:** when replying to a customer/process thread, set `for_central_agent=True` and pass `ReplyContext` (`customer_id`, `process_id`, `vendor_id`) into **`run_central_agent`**.

### Cross-party message flow

```
Customer message
  → Conversational agent → (optional) Specialist
    → Central agent
      → inbox:vendor_id / inbox:logistic_id / customer pair history
        → Business or Logistics chat
          → Central agent → Customer (polished)
```

WhatsApp ingress reuses the same interfaces via `backend/whatsapp/routers.py`.

---

## Engineering bottlenecks

These are the constraints that shaped the design and remain active areas for hardening.

| Bottleneck | Impact | Mitigation in codebase / ops |
|------------|--------|------------------------------|
| **LLM latency & cost** | Each turn may chain conversational → specialist → central → polish (multiple model calls). | Summarization caps history size; product cache TTL reduces repeated DB reads; tier gating limits agent surface area. |
| **Redis as hot session store** | Last-write-wins on `{user_id}:{vendor_id}` under concurrent requests; no transactions. | Critical payment/order facts persisted to Postgres; Paystack webhook idempotency table; reconciliation script. |
| **Process ambiguity** | Multiple open processes for the same product can mis-route handoffs. | Explicit `process_id` on central handoffs; `order_process_links` migration. |
| **Catalog cache vs DB** | Stale prices/stock in session cache vs live inventory. | TTL eviction; specialists refetch before purchase; vendor `mutate_vendor_catalog` syncs DB. |
| **Payment race conditions** | Money captured in Paystack before `create_order` succeeds (or the reverse). | Webhook + in-chat verification paths; `paystack_webhook_events`; documented in [`paystack_flow.md`](app/backend/readme/paystack_flow.md). |
| **Environment-sensitive Redis client** | `DEBUG=true` uses host/port/password; production uses `REDIS_URL`. Misconfiguration causes auth errors in deployment. | Document exact env vars; align Redis `--requirepass` with `REDIS_URL`. |
| **Frontend static build + API URL** | `NEXT_PUBLIC_*` is build-time; wrong values bake in wrong backend targets. | Explicit env configuration on Vercel/Dokploy; optional `/backend` rewrite proxy. |
| **OpenAI quota / model availability** | Production 429 errors surface as HTTP 500 to the UI. | Monitor provider billing; configure `MODEL_NAME` + keys per environment. |

Expanded failure-mode analysis: [`app/backend/readme/journey_risks_and_hardening.md`](app/backend/readme/journey_risks_and_hardening.md).

---

## Trade-offs

| We optimized for | We accepted |
|------------------|-------------|
| **Demonstrable multi-party flows** | Higher per-message latency vs a single LLM call |
| **Prompt-level business rules** (payment gates, routing) | Occasional model non-compliance; mitigated by tools and structured outputs |
| **Fast iteration on agent behavior** | Redis session as source of truth during active chats—not full event sourcing |
| **Provider flexibility** (OpenAI, Gemini, Anthropic) | Operational complexity tuning prompts per model family |
| **Rich demo UI** | Polling-based transparency panels (~3–4s refresh) rather than WebSockets |
| **Client-side currency conversion** | Approximate FX rates for display only; backend/DB remain authoritative in vendor currency |
| **Monorepo with separate deploy targets** | Two deployment surfaces (Vercel frontend, Docker backend) and env var discipline |
| **WhatsApp + web parity** | Shared interfaces increase coupling; WhatsApp-specific edge cases need separate testing |

---

## Evaluation

Ottobiz includes multiple evaluation layers—from routing smoke tests to full multi-party AI scenarios judged by an LLM.

### 1. Gold questions (routing smoke)

[`app/backend/scripts/gold_questions.json`](app/backend/scripts/gold_questions.json) — curated inputs per agent (product inquiry, purchase intent, bank transfer notification, delivery tracking, complaints) for manual or scripted routing checks.

### 2. Conversation test scaffolding

[`app/backend/tests/test_eval/test_conversations.py`](app/backend/tests/test_eval/test_conversations.py) — structured scenarios for customer–vendor and vendor–logistics flows, including edge-case placeholders (ambiguous product names, payment without order, concurrent conversations).

### 3. AI E2E harness (primary)

[`app/backend/tests/ai_tests/`](app/backend/tests/ai_tests/) — parametrized end-to-end tests against a **live API**:

- **Scenarios** (`scenarios.py`): product availability, payment with PDF receipts (valid, invalid, adversarial), logistics follow-ups, vendor coordination, etc.
- **History modes**: `fresh`, `short`, `long`, `mixed_prior_products` — stress context retention.
- **Simulated personas**: customer, vendor, and logistics lines generated via LLM; inbox polling for async central-agent messages.
- **LLM judge**: each run scored against a rubric with confidence and reasoning; failures include full transcripts.

```bash
cd app
pytest backend/tests/ai_tests/test_ai_e2e.py -v -m ai_e2e
```

Optional: point at a remote backend:

```bash
set AUTOBIZ_BASE_URL=https://your-api.example.com
pytest backend/tests/ai_tests/test_ai_e2e.py -m ai_e2e -k "fresh and product_available"
```

### 4. Observability

- **Logfire** instruments FastAPI and Pydantic AI when `LOGFIRE_TOKEN` is set.
- Agent trace utilities under `backend/chatbot/utils/` support stdout debugging during development.

---

## Edge cases

The system explicitly documents or tests for the following:

| Edge case | Behavior / risk |
|-----------|-----------------|
| **Payment before order exists** | Verification agents and webhooks must correlate reference/metadata; reconciliation script for gaps. |
| **Order without confirmed payment** | Central agent payment hard-gate; should not call `create_order` prematurely. |
| **Wrong or adversarial receipt PDF** | E2E scenarios include corrupt PDFs, plaintext non-receipts, wrong amount/product. |
| **Multiple open processes** | New messages may attach to wrong process if `process_id` omitted. |
| **Ambiguous product names** (“a phone”) | Product agent must clarify or search; upselling when SKU unavailable. |
| **Complaint without order reference** | Complaint agent de-escalates; may need clarification turn. |
| **Concurrent updates to same Redis key** | Last-write-wins; overlapping customer + webhook + central tool calls. |
| **Early process completion** | UI hides active work; model loses thread context. |
| **Stale product cache** | Customer quoted old price/stock; mitigated by TTL and refetch. |
| **Logistics without vendor “ready for pickup”** | Central prompt forbids premature logistics engagement. |
| **Self-handled vs carrier delivery** | Vendor chooses route; `finalize_vendor_delivery_route` persists party assignment. |
| **Redis flush / TTL expiry** | In-flight journeys lost unless critical fields were written to Postgres. |
| **Tier restrictions** | Free tier disables logistics/upselling/analytics unless `DEBUG=true`. |
| **Cross-origin frontend → API** | CORS enabled on backend; frontend requires correct `NEXT_PUBLIC_BACKEND_URL`. |
| **Provider quota exhaustion** | OpenAI 429 → HTTP 500; requires billing/monitoring, not code fallback. |

---

## Tech stack

| Layer | Technologies |
|-------|----------------|
| Backend | Python 3.11, FastAPI, Uvicorn, Pydantic AI |
| Data | PostgreSQL 15, Redis 7 |
| Frontend | Next.js 16, React 18, Tailwind CSS, TypeScript |
| Payments | Paystack (per-vendor keys, webhooks) |
| Messaging | WhatsApp Cloud API (optional) |
| Storage | Cloudflare R2 (optional, receipts/media) |
| Observability | Logfire |
| Deploy | Docker Compose, Dokploy, Vercel |

---

## Project structure

```
ottobiz/
├── app/                              # Backend (FastAPI)
│   ├── main.py
│   ├── requirements.txt
│   ├── docker-compose.local.yml      # Local Postgres + Redis + backend
│   ├── docker-compose.yml            # Production / Dokploy template
│   └── backend/
│       ├── api/routers/              # REST endpoints
│       ├── chatbot/
│       │   ├── agents/               # LLM agents
│       │   ├── interface/            # Chat orchestration entrypoints
│       │   └── prompts/
│       ├── db/                       # Migrations, cache, schemas
│       ├── payments/
│       ├── whatsapp/
│       ├── readme/                   # Architecture & Paystack docs
│       └── tests/
│           ├── ai_tests/             # E2E AI evaluation harness
│           └── test_eval/
├── frontend/                         # Next.js demo UI
│   ├── app/page.tsx
│   ├── lib/
│   └── Dockerfile
└── README.md
```

---

## Getting started

### Prerequisites

- Python 3.11+
- Node.js 20+
- Docker & Docker Compose
- LLM API key (OpenAI, Gemini, or Anthropic depending on `MODEL_NAME`)

### Backend (Docker — recommended)

```bash
cd app
cp .env.example .env   # configure MODEL_API_KEY, POSTGRES_*, REDIS_PASSWORD, etc.
docker compose -f docker-compose.local.yml up --build
```

API: `http://localhost:8000` · Docs: `http://localhost:8000/docs`

### Frontend (local dev against Docker backend)

```bash
cd frontend
cp .env.example .env
# NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
npm install
npm run dev
```

UI: `http://localhost:3000`

### Run tests

```bash
cd app
pytest backend/tests/
pytest backend/tests/ai_tests/test_ai_e2e.py -m ai_e2e -v
```

---

## Deployment

### Backend (Dokploy / Docker)

- Build from `app/` with `dockerfile`.
- Provide: `DATABASE_URL`, `REDIS_URL` (or `REDIS_SERVER_*` when `DEBUG=true`), `MODEL_API_KEY`, `MODEL_NAME`, `BASE_URL` (public API URL for webhooks and callbacks).
- Ensure Redis password in URL matches Redis service configuration.
- Postgres and Redis should live on an internal Docker network, not exposed publicly.

### Frontend (Vercel)

1. Set **Root Directory** to `frontend/`.
2. Set **`NEXT_PUBLIC_BACKEND_URL`** to your public backend URL (build-time).
3. Optionally set **`BACKEND_URL`** for server-side rewrites to `/backend/*`.
4. Do **not** use a custom `vercel-build` script—let Vercel run the default Next.js build once.

---

## Documentation

| Document | Description |
|----------|-------------|
| [`app/backend/readme/architectural_workflow.md`](app/backend/readme/architectural_workflow.md) | End-to-end backend journey |
| [`app/backend/readme/journey_risks_and_hardening.md`](app/backend/readme/journey_risks_and_hardening.md) | Failure modes and hardening |
| [`app/backend/readme/paystack_flow.md`](app/backend/readme/paystack_flow.md) | Payment initialization, webhooks, verification |
| [`FRONTEND_INTEGRATION.md`](FRONTEND_INTEGRATION.md) | Frontend ↔ API integration notes |

---

## License

See repository license file (if applicable).

## Author

Built as a portfolio-grade demonstration of multi-agent commerce automation, full-stack integration, and operable AI system design.
