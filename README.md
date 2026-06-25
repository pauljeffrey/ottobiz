# Ottobiz

**Ottobiz is an AI-powered (agentic) business assistant for small and medium businesses.** It helps run the full journey from a customer asking about a product, to payment, to delivery, to follow-up support, with separate AI agents handling each part of the job, and a live demo UI where you can watch it all happen.

Think of it as a digital operations team: a shop assistant talks to customers, a manager handles the store, a dispatcher coordinates delivery, and a coordinator makes sure everyone stays in sync.

---

## GitHub description

> AI platform that automates customer sales, vendor operations, and logistics — powered by specialized agents and a live three-pane demo UI.

---

## What the platform does

Many businesses sell through chat (WhatsApp, DMs, website) while managing stock, payments, and couriers separately. Ottobiz brings those pieces together:

1. **A customer** asks about products, places an order, pays, and tracks delivery.
2. **A vendor (business)** manages inventory, confirms payments, and prepares orders.
3. **A logistics partner** picks up and delivers.

Each party has their own chat. AI agents read and respond on their behalf, pass messages between parties when needed, and update the database (products, orders, stock) along the way.

The **demo frontend** lets you play all three roles at once: pick a customer persona and a business, chat in three panes side by side, and watch the catalog, active orders, and inventory update in real time.

---

## The AI agents

Ottobiz uses **many focused agents** instead of one generic chatbot. Each agent has a clear job.

| Agent | Role |
|-------|------|
| **Conversational agent** | The main shop assistant customers talk to. Understands intent and delegates to specialists. |
| **Product agent** | Finds products, checks stock and prices, shares payment details, notifies the vendor. |
| **Payment verification agent** | Confirms bank transfers or Paystack payments (including receipt uploads). |
| **Central agent** | The coordinator. Routes messages between customer, vendor, and logistics; creates orders after payment is confirmed; drives the deal forward. |
| **Business chat agent** | Helps vendors with day-to-day ops (analytics, inventory) or relays replies back through the central agent when coordinating with customers. |
| **Logistics agent** | Handles delivery questions and hands off to the central agent for multi-party coordination. |
| **Customer complaint agent** | Handles issues calmly and escalates to the vendor when needed. |
| **Upselling agent** | Suggests alternatives when something is out of stock. |
| **Marketing agent** | Recommends related products after a purchase. |

**How they work together:** The customer talks to the conversational agent. When something specific is needed (payment check, delivery, complaint), a specialist steps in. When the vendor or logistics company must be involved, the **central agent** takes over: it is the only agent that freely moves messages across all three sides.

**Important rules the system enforces:**
- Orders are not created until payment is verified.
- Logistics is not contacted until the vendor is ready.
- Vendor inventory changes only happen when the vendor clearly approves them.

---
## Decision & idea choices

- **Specialist agents, not one mega-bot** : Sales, payments, complaints, and logistics need different rules. Splitting agents keeps behavior predictable and easier to improve.
- **A central coordinator** : Cross-party messaging (customer ↔ vendor ↔ logistics) goes through one agent so nothing falls through the cracks.
- **Separate inboxes per party** : Vendors and couriers do not share the customer's chat thread; they get their own messages, like in real life.
- **Live demo UI** : Built to show stakeholders how the backend behaves, not just to chat in isolation.
- **Payments via Paystack** : Each business can use its own Paystack account; webhooks confirm payment even if the customer leaves chat to pay (still under development).
- **Tiered product vision** : Free, Gold, and Platinum tiers gate features like logistics and analytics for a future commercial product.

---

## Architectural choices

| Layer | What it does |
|-------|----------------|
| **Frontend** (Next.js) | Three chat panes, persona picker, live catalog/orders/inventory panels, currency selector, reports |
| **Backend** (FastAPI) | Chat APIs, agent orchestration, analytics, inventory, payments |
| **Database** (PostgreSQL) | Products, orders, businesses, payment records, chat summaries |
| **Session store** (Redis) | Active conversations, open orders-in-progress, message inboxes |
| **LLM layer** | Agents with structured tools; supports OpenAI, Gemini, or Anthropic |

**Deployment:** Backend + database on Docker; frontend on Vercel.

For deeper technical flow, see [`app/backend/readme/architectural_workflow.md`](app/backend/readme/architectural_workflow.md).

---

## Multi-agent orchestration (in plain terms)

1. **Customer sends a message** → conversational agent responds or calls a specialist.
2. **Specialist finishes its task** → if another party must act, it notifies the central agent.
3. **Central agent decides** who goes next (customer, vendor, or logistics), updates order/process state, and sends the message.
4. **Vendor or logistics replies** in their own chat → business agent either handles it directly (e.g. "show my inventory") or forwards it to the central agent for coordination.
5. **Customer sees a polished reply** → long internal reasoning is never dumped on the shopper.

This hub-and-spoke design keeps customer-facing chat friendly while still automating the messy back-and-forth between business and delivery partners.

---

## Engineering bottlenecks

| Challenge | Why it matters |
|-----------|----------------|
| **Multiple AI calls per message** | Rich behavior costs time and API credits; chat history is summarized to stay within limits. |
| **Session state in memory (Redis)** | Fast for live chat, but concurrent updates can clash; critical data (orders, payments) is saved to the database. |
| **Payment timing** | Customer may pay before the system creates an order; webhooks and receipt checks cover both paths. |
| **Stale product info** | Prices shown earlier may change; agents re-check stock before confirming a sale. |

---

## Trade-offs

| Chose | Gave up |
|-------|---------|
| Realistic multi-party automation | Slower replies than a single simple chatbot |
| Visible demo (catalog, orders, agents) | UI refreshes on a timer instead of instant push updates |
| Flexible AI providers | More setup per environment |
| Strong business rules in agents | Occasional model mistakes; guarded by tools and checks |
| Client-side currency display for demos | Display rates are approximate, not live forex |

---

## Evaluation

Quality is tested in several ways:

- **Gold questions**: Standard prompts (product inquiry, payment, complaint) to check each agent routes correctly.
- **Conversation scenarios**: Scripted customer–vendor and vendor–logistics flows.
- **End-to-end AI tests**: Simulated customers, vendors, and couriers chat with a live API; an AI judge scores whether the outcome met the goal (including tricky cases like fake or wrong receipts).
- **Observability**: Optional Logfire tracing for debugging agent behavior in production.

---

## Edge cases handled (or planned for)

- Customer pays but no order exists yet → webhook + receipt verification reconcile payment
- Product out of stock → upselling agent suggests alternatives
- Vague product request ("I want a phone") → agent clarifies or searches catalog
- Complaint with no order number → agent asks for details before escalating
- Wrong or fake payment receipt → payment agent rejects or flags
- Multiple open enquiries at once → processes tracked separately to avoid mixing orders
- Vendor chooses self-delivery vs courier → central agent records the choice and routes accordingly
- Long conversations → older messages summarized so agents stay focused

---

## Tech stack

Python · FastAPI · PostgreSQL · Redis · Pydantic AI · Next.js · Tailwind CSS · Paystack · WhatsApp (optional) · Docker · Vercel

---

## Getting started

**Backend**
```bash
cd app
cp .env.example .env   # add your AI API key and database settings
docker compose -f docker-compose.local.yml up --build
```
→ API at `http://localhost:8000` · Docs at `/docs`

**Frontend**
```bash
cd frontend
cp .env.example .env   # NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
npm install && npm run dev
```
→ UI at `http://localhost:3000`

---

## Deployment

| Service | Where |
|---------|--------|
| Backend, Postgres, Redis | Docker |
| Frontend | Vercel (set root directory to `frontend/`, add `NEXT_PUBLIC_BACKEND_URL`) |

---

Built as a portfolio demonstration of multi-agent commerce automation — from first message to delivered order.
