import type { Metadata } from "next"
import Link from "next/link"
import { SiteNav } from "@/components/site-nav"

export const metadata: Metadata = {
  title: "How to Use — Ottobiz",
  description: "How to get the most out of the Ottobiz live demo.",
}

export default function HowToUsePage() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50">
      <SiteNav active="how-to-use" />

      <main className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
        {/* Hero banner */}
        <div className="bg-gradient-to-r from-teal-600 to-blue-600 rounded-xl p-6 text-white">
          <h1 className="text-2xl font-bold mb-1">How to use Ottobiz</h1>
          <p className="text-teal-100 text-sm leading-relaxed">
            Ottobiz is an AI-powered business simulation platform. Three AI agents — a{" "}
            <strong>Customer</strong>, a <strong>Business Manager</strong>, and a{" "}
            <strong>Logistics Coordinator</strong> — interact in real time, driven by your
            prompts. Follow the steps below to get started.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {/* Step 1 */}
          <div className="bg-white rounded-xl shadow-md p-5 border-t-4 border-blue-500">
            <div className="flex items-center gap-2 mb-3">
              <span className="bg-blue-100 text-blue-700 font-bold text-sm px-2.5 py-0.5 rounded-full">
                Step 1
              </span>
              <h3 className="font-semibold text-gray-800">Select personas</h3>
            </div>
            <ul className="text-sm text-gray-600 space-y-1.5 leading-relaxed">
              <li>
                • On the <strong>Demo</strong> page pick a <strong>User persona</strong> (the
                customer).
              </li>
              <li>• Pick a <strong>Business persona</strong> (the vendor/store).</li>
              <li>
                • A <strong>Logistics carrier</strong> is automatically linked to the business —
                shown in the "Linked logistics" card.
              </li>
            </ul>
          </div>

          {/* Step 2 */}
          <div className="bg-white rounded-xl shadow-md p-5 border-t-4 border-green-500">
            <div className="flex items-center gap-2 mb-3">
              <span className="bg-green-100 text-green-700 font-bold text-sm px-2.5 py-0.5 rounded-full">
                Step 2
              </span>
              <h3 className="font-semibold text-gray-800">Chat with agents</h3>
            </div>
            <ul className="text-sm text-gray-600 space-y-1.5 leading-relaxed">
              <li>
                • <strong>Customer Chat</strong> — type as the customer. Ask about products,
                place orders, track deliveries, or request refunds.
              </li>
              <li>
                • <strong>Business Chat</strong> — type as the business manager. Manage
                inventory, approve requests, view analytics.
              </li>
              <li>
                • <strong>Logistics Chat</strong> — the logistics agent posts updates here
                automatically. You can also query it directly.
              </li>
            </ul>
          </div>

          {/* Step 3 */}
          <div className="bg-white rounded-xl shadow-md p-5 border-t-4 border-purple-500">
            <div className="flex items-center gap-2 mb-3">
              <span className="bg-purple-100 text-purple-700 font-bold text-sm px-2.5 py-0.5 rounded-full">
                Step 3
              </span>
              <h3 className="font-semibold text-gray-800">Watch the live panels</h3>
            </div>
            <ul className="text-sm text-gray-600 space-y-1.5 leading-relaxed">
              <li>
                • <strong>Product Catalog</strong> — live product listings for the selected
                business, refreshed automatically every few seconds.
              </li>
              <li>
                • <strong>Active Orders</strong> — current open orders; updates as the customer
                and business interact.
              </li>
              <li>• <strong>Products Discussed</strong> — items mentioned in the customer conversation.</li>
              <li>
                • <strong>Active Processes &amp; Inventory</strong> — background tasks and stock
                changes in real time.
              </li>
            </ul>
          </div>

          {/* Currency */}
          <div className="bg-white rounded-xl shadow-md p-5 border-t-4 border-yellow-500">
            <div className="flex items-center gap-2 mb-3">
              <span className="bg-yellow-100 text-yellow-700 font-bold text-sm px-2.5 py-0.5 rounded-full">
                Tip
              </span>
              <h3 className="font-semibold text-gray-800">Currency selector</h3>
            </div>
            <ul className="text-sm text-gray-600 space-y-1.5 leading-relaxed">
              <li>• The <strong>coin icon</strong> in the top-right header opens the currency dropdown.</li>
              <li>
                • Choose USD, NGN, GBP, EUR, CAD, AUD, or ZAR — all prices across the UI are
                converted instantly.
              </li>
              <li>• Your choice is saved in the browser (localStorage) across sessions.</li>
              <li>
                • Conversion is done on the frontend using approximate exchange rates; backend
                data is always stored in USD.
              </li>
            </ul>
          </div>

          {/* Reports tab */}
          <div className="bg-white rounded-xl shadow-md p-5 border-t-4 border-indigo-500">
            <div className="flex items-center gap-2 mb-3">
              <span className="bg-indigo-100 text-indigo-700 font-bold text-sm px-2.5 py-0.5 rounded-full">
                Tip
              </span>
              <h3 className="font-semibold text-gray-800">Reports &amp; Data tab</h3>
            </div>
            <ul className="text-sm text-gray-600 space-y-1.5 leading-relaxed">
              <li>• Switch to the <strong>Reports &amp; data</strong> tab to pull deeper analytics.</li>
              <li>• <strong>Business Analytics</strong> — revenue, top products, order stats for the selected business.</li>
              <li>• <strong>User Analytics</strong> — spend history and behaviour for the selected user persona.</li>
              <li>• <strong>Inventory</strong> — current stock levels.</li>
              <li>• <strong>Supply Chain</strong> — order pipeline and delivery metrics.</li>
              <li>• Click each "Get ..." button once to load it — after that it keeps itself fresh automatically.</li>
            </ul>
          </div>

          {/* API key & session */}
          <div className="bg-white rounded-xl shadow-md p-5 border-t-4 border-red-400">
            <div className="flex items-center gap-2 mb-3">
              <span className="bg-red-100 text-red-600 font-bold text-sm px-2.5 py-0.5 rounded-full">
                Advanced
              </span>
              <h3 className="font-semibold text-gray-800">API key &amp; session reset</h3>
            </div>
            <ul className="text-sm text-gray-600 space-y-1.5 leading-relaxed">
              <li>
                • The <strong>API Key</strong> field in the header authenticates your requests to
                the backend — leave blank to use the default.
              </li>
              <li>
                • <strong>Clear Redis session</strong> wipes the in-memory conversation context on
                the backend, giving you a fresh start without reloading the page.
              </li>
              <li>• Use it when switching between very different scenarios to avoid the AI mixing up context.</li>
            </ul>
          </div>
        </div>

        {/* Sample prompts */}
        <div className="bg-white rounded-xl shadow-md p-5">
          <h3 className="font-semibold text-gray-800 mb-3">Sample prompts to try</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
            {[
              { label: "Customer", color: "blue", prompt: "Show me all available products under $50." },
              { label: "Customer", color: "blue", prompt: "I'd like to order 2 units of the cheapest item." },
              { label: "Customer", color: "blue", prompt: "Where is my last order?" },
              { label: "Business", color: "orange", prompt: "Give me a summary of today's orders." },
              { label: "Business", color: "orange", prompt: "Restock the top-selling item with 100 units." },
              { label: "Logistics", color: "green", prompt: "What deliveries are pending for this business?" },
            ].map(({ label, color, prompt }) => (
              <div key={prompt} className={`rounded-lg border p-3 text-sm bg-${color}-50 border-${color}-200`}>
                <span className={`text-xs font-semibold text-${color}-700 uppercase tracking-wide`}>
                  {label}
                </span>
                <p className="text-gray-700 mt-1 italic">"{prompt}"</p>
              </div>
            ))}
          </div>
        </div>

        <div className="text-center pb-6">
          <Link
            href="/"
            className="inline-block bg-blue-600 hover:bg-blue-700 text-white font-medium px-5 py-2.5 rounded-lg transition-colors"
          >
            Go to the demo →
          </Link>
        </div>
      </main>
    </div>
  )
}
