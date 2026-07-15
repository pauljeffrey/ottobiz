import type { Metadata } from "next"
import Link from "next/link"
import { SiteNav } from "@/components/site-nav"

export const metadata: Metadata = {
  title: "About — Ottobiz",
  description: "What Ottobiz is, how it's built, and why — in plain terms.",
}

const AGENTS: { name: string; role: string }[] = [
  { name: "Conversational agent", role: "The main shop assistant customers talk to. Figures out what the customer wants and calls in a specialist when needed." },
  { name: "Product agent", role: "Looks up products, checks stock and price, and shares payment details with the customer." },
  { name: "Payment verification agent", role: "Confirms a payment really happened — either a Paystack payment or an uploaded bank transfer receipt." },
  { name: "Central agent", role: "The coordinator. Passes messages between customer, vendor, and logistics, and creates the order once payment is confirmed." },
  { name: "Business chat agent", role: "Helps the vendor with day-to-day tasks (analytics, inventory) and relays messages from customers/logistics." },
  { name: "Logistics agent", role: "Answers delivery questions and loops in the central agent when other parties need to be involved." },
  { name: "Customer complaint agent", role: "Handles complaints calmly and escalates to the vendor when it can't resolve something alone." },
  { name: "Upselling & marketing agents", role: "Suggest alternatives when something is out of stock, and recommend related products after a purchase." },
]

const STACK: { name: string; why: string }[] = [
  { name: "Python + FastAPI", why: "The backend API — fast, async, and a natural fit for calling multiple AI agents per request." },
  { name: "Pydantic AI", why: "Gives each agent a typed, structured toolbox instead of loose text parsing — fewer surprises from the LLM." },
  { name: "PostgreSQL", why: "The source of truth: products, orders, businesses, and payment records live here." },
  { name: "Redis", why: "Fast, short-lived memory for active conversations and open orders-in-progress — cleared between demo sessions." },
  { name: "Next.js + Tailwind CSS", why: "The three-pane demo UI you're using right now, plus the live catalog/orders panels." },
  { name: "Paystack", why: "Real payment processing per vendor, with webhook confirmation so a payment counts even if the customer leaves the chat." },
  { name: "Docker", why: "Packages the backend, database, and Redis so they run the same way anywhere." },
]

export default function AboutPage() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50">
      <SiteNav active="about" />

      <main className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {/* Hero */}
        <div className="bg-gradient-to-r from-blue-600 to-purple-600 rounded-xl p-6 text-white">
          <h1 className="text-2xl font-bold mb-2">About Ottobiz</h1>
          <p className="text-blue-50 text-sm leading-relaxed max-w-3xl">
            Ottobiz is an AI-powered assistant for small and medium businesses that sell through
            chat. It plays out the whole journey — a customer asking about a product, paying for
            it, getting it delivered, and following up afterwards — with a separate AI agent
            handling each part of the job. This page is a portfolio walkthrough of how it's built
            and why, in plain language.
          </p>
        </div>

        {/* What it does */}
        <section className="bg-white rounded-xl shadow-md p-5">
          <h2 className="font-semibold text-gray-800 text-lg mb-3">What it does</h2>
          <p className="text-sm text-gray-600 leading-relaxed mb-3">
            Many small businesses sell over WhatsApp, DMs, or a website chat widget, while
            juggling stock, payments, and couriers separately by hand. Ottobiz brings those three
            jobs together into one system:
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="rounded-lg border border-blue-200 bg-blue-50 p-3">
              <p className="text-xs font-semibold text-blue-700 uppercase tracking-wide mb-1">Customer</p>
              <p className="text-sm text-gray-700">Asks about products, places an order, pays, and tracks delivery.</p>
            </div>
            <div className="rounded-lg border border-green-200 bg-green-50 p-3">
              <p className="text-xs font-semibold text-green-700 uppercase tracking-wide mb-1">Vendor</p>
              <p className="text-sm text-gray-700">Manages inventory, confirms payments, and prepares orders.</p>
            </div>
            <div className="rounded-lg border border-orange-200 bg-orange-50 p-3">
              <p className="text-xs font-semibold text-orange-700 uppercase tracking-wide mb-1">Logistics</p>
              <p className="text-sm text-gray-700">Picks up and delivers the order.</p>
            </div>
          </div>
          <p className="text-sm text-gray-600 leading-relaxed mt-3">
            Each party has their own chat, and this demo lets you play all three roles at once —
            pick a customer and a business, chat in three panes side by side, and watch the
            catalog, orders, and inventory update as the agents work.
          </p>
        </section>

        {/* How it works */}
        <section className="bg-white rounded-xl shadow-md p-5">
          <h2 className="font-semibold text-gray-800 text-lg mb-3">How it works, in plain terms</h2>
          <ol className="text-sm text-gray-600 space-y-2 leading-relaxed list-decimal list-inside">
            <li>The customer sends a message — the conversational agent replies, or hands off to a specialist (product lookup, payment check, complaint).</li>
            <li>When the vendor or the delivery company needs to be told something, the <strong>central agent</strong> steps in — it's the only agent that talks across all three sides.</li>
            <li>The central agent decides who hears about it next, updates the order in the database, and sends the message.</li>
            <li>The vendor or logistics company replies in their own chat — either handled directly ("show my inventory") or relayed back through the central agent.</li>
            <li>The customer only ever sees a clean, final reply — the back-and-forth between vendor and courier stays behind the scenes.</li>
          </ol>
          <p className="text-sm text-gray-600 leading-relaxed mt-3">
            Two rules are enforced everywhere: an order is never created until payment is
            confirmed, and logistics is never contacted until the vendor is ready to hand the
            order off.
          </p>
        </section>

        {/* Agents */}
        <section className="bg-white rounded-xl shadow-md p-5">
          <h2 className="font-semibold text-gray-800 text-lg mb-3">Meet the agents</h2>
          <p className="text-sm text-gray-600 leading-relaxed mb-3">
            Instead of one do-everything chatbot, Ottobiz uses several small, focused agents.
            Splitting the work up keeps each agent's behaviour predictable and easy to reason
            about.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {AGENTS.map((a) => (
              <div key={a.name} className="rounded-lg border border-gray-200 p-3">
                <p className="text-sm font-semibold text-gray-800">{a.name}</p>
                <p className="text-sm text-gray-600 mt-1">{a.role}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Tech stack */}
        <section className="bg-white rounded-xl shadow-md p-5">
          <h2 className="font-semibold text-gray-800 text-lg mb-3">What it's built with</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {STACK.map((s) => (
              <div key={s.name} className="rounded-lg border border-gray-200 p-3">
                <p className="text-sm font-semibold text-gray-800">{s.name}</p>
                <p className="text-sm text-gray-600 mt-1">{s.why}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Honest trade-offs */}
        <section className="bg-white rounded-xl shadow-md p-5">
          <h2 className="font-semibold text-gray-800 text-lg mb-3">Built to be transparent</h2>
          <p className="text-sm text-gray-600 leading-relaxed mb-3">
            This is a portfolio project, and it's set up to be looked at, not hidden behind a
            login. A few deliberate choices worth knowing about:
          </p>
          <ul className="text-sm text-gray-600 space-y-2 leading-relaxed">
            <li>• <strong>Demo data resets on restart</strong> — the same set of sample users, businesses, and products come back every time the backend restarts, so the demo is always in a known, working state.</li>
            <li>• <strong>Live panels refresh on a timer</strong> (every few seconds) rather than pushing instant updates — simpler to build and plenty fast for a demo.</li>
            <li>• <strong>No login screen</strong> — you pick a persona instead of signing in, so you can jump straight into any of the three roles.</li>
            <li>• <strong>Currency conversion is approximate</strong> and happens in the browser for display only; the backend always stores amounts in USD.</li>
          </ul>
        </section>

        <div className="text-center pb-6 flex flex-wrap items-center justify-center gap-3">
          <Link
            href="/how-to-use"
            className="inline-block bg-white border border-gray-300 hover:bg-gray-50 text-gray-700 font-medium px-5 py-2.5 rounded-lg transition-colors"
          >
            How to use the demo
          </Link>
          <Link
            href="/"
            className="inline-block bg-blue-600 hover:bg-blue-700 text-white font-medium px-5 py-2.5 rounded-lg transition-colors"
          >
            Go to the demo →
          </Link>
          <a
            href="https://github.com/pauljeffrey/ottobiz"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-block bg-gray-900 hover:bg-black text-white font-medium px-5 py-2.5 rounded-lg transition-colors"
          >
            View source on GitHub
          </a>
        </div>
      </main>
    </div>
  )
}
