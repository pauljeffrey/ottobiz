"use client"

import type React from "react"
import { useState, useRef, useEffect, useSyncExternalStore } from "react"
import Link from "next/link"
import { ChatMessageBody } from "@/components/chat-message-body"
import { API_BASE } from "@/lib/api-base"
import {
  useTransparencyPanels,
  type SessionOrderRow,
} from "@/lib/use-transparency-panels"
import {
  CURRENCIES,
  type CurrencyCode,
  formatAmount,
  rewriteTextCurrency,
} from "@/lib/currency"
import {
  Send,
  Mic,
  MicOff,
  Paperclip,
  User,
  Building2,
  Truck,
  TrendingUp,
  Package,
  BarChart3,
  Key,
  X,
  ImageIcon,
  Volume2,
  FileText,
  ShoppingCart,
  Users,
  RotateCcw,
  ChevronDown,
  ChevronRight,
  RefreshCw,
  Coins,
} from "lucide-react"

const TRANSPARENCY_POLL_MS = 4000
// All API calls go through API_BASE (= NEXT_PUBLIC_BACKEND_URL or the same-origin /backend proxy).
// Never use process.env.BACKEND_URL here — it is a server-side variable and is always undefined
// in this client component, causing every fetch to use an empty/wrong base URL.

/** Stable placeholder time for welcome rows — avoids SSR/client `Date` hydration mismatches. */
const STATIC_WELCOME_TS = new Date("2000-01-01T12:00:00.000Z")

interface ChatMessage {
  id: string
  content: string
  sender: "user" | "ai"
  timestamp: Date
  customer_id?: string
  product_name?: string
  order_id?: string
  business_id?: string
  _inbox?: boolean
  _rawMessage?: string
}

interface Persona {
  id: string
  name: string
}

const predefinedUsers: Persona[] = [
  { id: "00000000-0000-0000-0000-000000000001", name: "John Doe" },
  { id: "00000000-0000-0000-0000-000000000002", name: "Sarah Johnson" },
  { id: "00000000-0000-0000-0000-000000000003", name: "Michael Chen" },
  { id: "00000000-0000-0000-0000-000000000004", name: "Emily Rodriguez" },
  { id: "00000000-0000-0000-0000-000000000005", name: "David Wilson" },
  { id: "00000000-0000-0000-0000-000000000006", name: "Lisa Thompson" },
]

const predefinedBusinesses: Persona[] = [
  { id: "00000000-0000-0000-0001-000000000001", name: "Donrey Fashion" },
  { id: "00000000-0000-0000-0001-000000000002", name: "Junae Cosmetics" },
  { id: "00000000-0000-0000-0001-000000000003", name: "Manny Gadgets" },
  { id: "00000000-0000-0000-0001-000000000004", name: "Tesla Tech" },
  { id: "00000000-0000-0000-0001-000000000005", name: "Kemi Surprises" },
]

const predefinedLogistics: Persona[] = [
  { id: "00000000-0000-0000-0002-000000000001", name: "Fast Delivery Co" },
  { id: "00000000-0000-0000-0002-000000000002", name: "Express Logistics" },
  { id: "00000000-0000-0000-0002-000000000003", name: "Quick Ship" },
]

function sessionOrderQtyHint(o: SessionOrderRow): string | null {
  const m = o.metadata
  const pa = o.product_attributes
  const fromMeta =
    m && typeof m === "object" && "quantity" in m ? (m as { quantity?: unknown }).quantity : undefined
  const fromPa =
    pa && typeof pa === "object" && "quantity" in pa
      ? (pa as { quantity?: unknown }).quantity
      : undefined
  const q = fromMeta ?? fromPa
  if (q == null || q === "") return null
  return String(q)
}

/** true only after client hydration; keeps SSR + first client pass in sync for boolean DOM props like `disabled`. */
function useHydrated(): boolean {
  return useSyncExternalStore(
    (onStoreChange) => {
      onStoreChange()
      return () => {}
    },
    () => true,
    () => false,
  )
}

export default function Page() {
  // Customer chat state
  const [customerMessages, setCustomerMessages] = useState<ChatMessage[]>([
    {
      id: "welcome-customer",
      content: "Hello! Select a user and business to start chatting.",
      sender: "ai",
      timestamp: STATIC_WELCOME_TS,
    },
  ])
  const [customerInput, setCustomerInput] = useState("")
  const [selectedUser, setSelectedUser] = useState<Persona | null>(null)
  const [isCustomerLoading, setIsCustomerLoading] = useState(false)

  // Business chat state
  const [businessMessages, setBusinessMessages] = useState<ChatMessage[]>([
    {
      id: "welcome-business",
      content: "Select a business to start chatting.",
      sender: "ai",
      timestamp: STATIC_WELCOME_TS,
    },
  ])
  const [businessInput, setBusinessInput] = useState("")
  const [selectedBusiness, setSelectedBusiness] = useState<Persona | null>(null)
  const [isBusinessLoading, setIsBusinessLoading] = useState(false)

  // Logistics chat state
  const [logisticsMessages, setLogisticsMessages] = useState<ChatMessage[]>([
    {
      id: "welcome-logistics",
      content: "Logistics is linked automatically when you pick a business.",
      sender: "ai",
      timestamp: STATIC_WELCOME_TS,
    },
  ])
  const [logisticsInput, setLogisticsInput] = useState("")
  const [selectedLogistics, setSelectedLogistics] = useState<Persona | null>(null)
  const [isLogisticsLoading, setIsLogisticsLoading] = useState(false)

  // Analytics state
  const [businessAnalytics, setBusinessAnalytics] = useState<any>(null)
  const [userAnalytics, setUserAnalytics] = useState<any>(null)
  const [inventoryData, setInventoryData] = useState<any>(null)
  const [supplyChainData, setSupplyChainData] = useState<any>(null)
  const [isLoadingAnalytics, setIsLoadingAnalytics] = useState(false)

  const [customerSessionId, setCustomerSessionId] = useState("")
  const [businessSessionId, setBusinessSessionId] = useState("")
  const [logisticsSessionId, setLogisticsSessionId] = useState("")

  const [apiKey, setApiKey] = useState("")

  const [selectedCurrency, setSelectedCurrency] = useState<CurrencyCode>("NGN")

  useEffect(() => {
    const saved = localStorage.getItem("ottobiz_currency") as CurrencyCode | null
    if (saved && CURRENCIES.some((c) => c.code === saved)) setSelectedCurrency(saved)
  }, [])

  useEffect(() => {
    localStorage.setItem("ottobiz_currency", selectedCurrency)
  }, [selectedCurrency])

  const [sbInventoryActivityOpen, setSbInventoryActivityOpen] = useState(true)

  const {
    topProducts,
    agentProducts,
    agentProcesses,
    inventoryActivity,
    activeSessionOrders,
    refreshing: transparencyRefreshing,
    updatedAt: transparencyUpdatedAt,
    fetchError: transparencyFetchError,
    loadAll: refreshTransparency,
    loadSession: refreshSessionPanels,
  } = useTransparencyPanels(
    API_BASE,
    selectedBusiness?.id,
    selectedUser?.id,
    TRANSPARENCY_POLL_MS,
  )

  /** Chats + sidebar vs compact reports — avoids long vertical scroll. */
  const [workspaceTab, setWorkspaceTab] = useState<"chats" | "reports">("chats")

  const customerChatScrollRef = useRef<HTMLDivElement>(null)
  const businessChatScrollRef = useRef<HTMLDivElement>(null)
  const logisticsChatScrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setCustomerSessionId((s) => s.trim() || crypto.randomUUID())
    setBusinessSessionId((s) => s.trim() || crypto.randomUUID())
    setLogisticsSessionId((s) => s.trim() || crypto.randomUUID())
  }, [])

  const scrollChatPane = (containerRef: React.RefObject<HTMLDivElement | null>) => {
    const el = containerRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }

  /**
   * Some browsers auto-scroll the whole page to "help" keep a focused input
   * visible whenever nearby content changes (e.g. sending a chat message).
   * That fights the user, who should stay exactly where they were unless they
   * scroll themselves — snapshot + restore window scroll across the next
   * couple of render/layout passes to cancel that out.
   */
  const holdScrollPosition = () => {
    const y = window.scrollY
    const restore = () => {
      if (window.scrollY !== y) window.scrollTo(0, y)
    }
    requestAnimationFrame(() => {
      restore()
      requestAnimationFrame(restore)
    })
  }

  useEffect(() => {
    scrollChatPane(customerChatScrollRef)
  }, [customerMessages, isCustomerLoading])

  useEffect(() => {
    scrollChatPane(businessChatScrollRef)
  }, [businessMessages, isBusinessLoading])

  useEffect(() => {
    scrollChatPane(logisticsChatScrollRef)
  }, [logisticsMessages, isLogisticsLoading])

  useEffect(() => {
    if (!selectedBusiness) {
      setSelectedLogistics(null)
      return
    }
    let cancelled = false
    ;(async () => {
      try {
        const res = await fetch(
          `${API_BASE}/api/v1/business/delivery-partner/${selectedBusiness.id}`,
        )
        if (!res.ok) return
        const j = await res.json()
        if (cancelled) return
        const id = j.partner_logistic_id as string | undefined
        const name = j.partner_name as string | undefined
        if (id) {
          const persona =
            predefinedLogistics.find((p) => p.id === id) ?? { id, name: name || id }
          setSelectedLogistics(persona)
        } else {
          setSelectedLogistics(null)
        }
        setLogisticsSessionId(crypto.randomUUID())
      } catch {
        if (!cancelled) setSelectedLogistics(null)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [selectedBusiness])

  useEffect(() => {
    if (!selectedUser || !selectedBusiness) return
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/customer/inbox/${selectedUser.id}`)
        const data = await res.json()
        if (data.messages?.length > 0) {
          const relevant = data.messages.filter(
            (m: { business_id?: string }) =>
              !m.business_id || m.business_id === selectedBusiness?.id
          )
          const incoming = relevant.map(
            (m: { message: string; sender?: string; business_id?: string }, i: number) => ({
              id: `customer-inbox-${Date.now()}-${i}`,
              content: m.message,
              sender: "ai" as const,
              timestamp: new Date(),
              business_id: m.business_id,
              _inbox: true,
            })
          )
          if (incoming.length > 0) setCustomerMessages((prev) => [...prev, ...incoming])
        }
      } catch (_) {}
    }, 3000)
    return () => clearInterval(interval)
  }, [selectedUser, selectedBusiness])

  useEffect(() => {
    if (!selectedBusiness && !selectedLogistics) return

    const interval = setInterval(async () => {
      if (selectedBusiness) {
        try {
          const res = await fetch(`${API_BASE}/api/v1/business/inbox/${selectedBusiness.id}`)
          const data = await res.json()
          if (data.messages?.length > 0) {
            const incoming = data.messages.map((m: { message: string; sender: string; customer_id?: string; product_name?: string; order_id?: string; business_id?: string }, i: number) => {
              const ctx = [m.customer_id, m.product_name, m.order_id].filter(Boolean).join(" · ")
              return {
                id: `inbox-${Date.now()}-${i}`,
                content: ctx ? `[Re: ${ctx}] [From ${m.sender}] ${m.message}` : `[From ${m.sender}] ${m.message}`,
                sender: "ai" as const,
                timestamp: new Date(),
                customer_id: m.customer_id,
                product_name: m.product_name,
                order_id: m.order_id,
                business_id: m.business_id,
                _inbox: true,
                _rawMessage: m.message,
              }
            })
            setBusinessMessages((prev) => [...prev, ...incoming])
          }
        } catch (_) {}
      }

      if (selectedLogistics) {
        try {
          const res = await fetch(`${API_BASE}/api/v1/logistics/inbox/${selectedLogistics.id}`)
          const data = await res.json()
          if (data.messages?.length > 0) {
            const incoming = data.messages.map((m: { message: string; sender: string; customer_id?: string; product_name?: string; order_id?: string; business_id?: string }, i: number) => {
              const ctx = [m.customer_id, m.product_name, m.order_id].filter(Boolean).join(" · ")
              return {
                id: `inbox-${Date.now()}-${i}`,
                content: ctx ? `[Re: ${ctx}] [From ${m.sender}] ${m.message}` : `[From ${m.sender}] ${m.message}`,
                sender: "ai" as const,
                timestamp: new Date(),
                customer_id: m.customer_id,
                product_name: m.product_name,
                order_id: m.order_id,
                business_id: m.business_id,
                _inbox: true,
                _rawMessage: m.message,
              }
            })
            setLogisticsMessages((prev) => [...prev, ...incoming])
          }
        } catch (_) {}
      }
    }, 3000)

    return () => clearInterval(interval)
  }, [selectedBusiness, selectedLogistics])

  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || [])
    setSelectedFiles((prev) => [...prev, ...files])
    if (event.target) {
      event.target.value = ""
    }
  }

  const removeFile = (index: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index))
  }

  // Customer chat handlers
  const handleCustomerSend = async () => {
    if ((!customerInput.trim() && selectedFiles.length === 0) || !selectedUser || !selectedBusiness) return

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      content: customerInput || "File(s) uploaded",
      sender: "user",
      timestamp: new Date(),
    }

    setCustomerMessages((prev) => [...prev, userMessage])
    const message = customerInput
    const currentFiles = [...selectedFiles]
    setCustomerInput("")
    setSelectedFiles([])
    setIsCustomerLoading(true)

    try {
      let sid = customerSessionId.trim()
      if (!sid) {
        sid = crypto.randomUUID()
        setCustomerSessionId(sid)
      }
      const formData = new FormData()
      formData.append("user_id", selectedUser.id)
      formData.append("vendor_id", selectedBusiness.id)
      formData.append("session_id", sid)
      formData.append("message", message ?? "")

      if (apiKey.trim()) {
        formData.append("api_key", apiKey)
      }

      currentFiles.forEach((file) => {
        formData.append("files", file, file.name || "upload")
      })

      const response = await fetch(`${API_BASE}/api/v1/customer/chat`, {
        method: "POST",
        body: formData,
      })

      if (!response.ok) {
        const errText = await response.text()
        throw new Error(errText || response.statusText || `HTTP ${response.status}`)
      }

      const data = await response.json()
      const aiMessage: ChatMessage = {
        id: (Date.now() + 1).toString(),
        content: data.message || "No response",
        sender: "ai",
        timestamp: new Date(),
      }
      setCustomerMessages((prev) => [...prev, aiMessage])
    } catch (error) {
      console.error("Error:", error)
      const errorMessage: ChatMessage = {
        id: (Date.now() + 1).toString(),
        content: `Error: ${error instanceof Error ? error.message : "Unknown error"}`,
        sender: "ai",
        timestamp: new Date(),
      }
      setCustomerMessages((prev) => [...prev, errorMessage])
    } finally {
      setIsCustomerLoading(false)
      void refreshTransparency()
    }
  }

  // Business chat handlers
  const handleBusinessSend = async () => {
    if (!businessInput.trim() || !selectedBusiness) return

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      content: businessInput,
      sender: "user",
      timestamp: new Date(),
    }

    setBusinessMessages((prev) => [...prev, userMessage])
    const message = businessInput
    setBusinessInput("")
    setIsBusinessLoading(true)

    try {
      let sid = businessSessionId.trim()
      if (!sid) {
        sid = crypto.randomUUID()
        setBusinessSessionId(sid)
      }
      const response = await fetch(`${API_BASE}/api/v1/business/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          business_id: selectedBusiness.id,
          session_id: sid,
          sender: "business",
          message: message,
          api_key: apiKey || undefined,
        }),
      })

      const data = await response.json()
      const aiMessage: ChatMessage = {
        id: (Date.now() + 1).toString(),
        content: data.message || "No response",
        sender: "ai",
        timestamp: new Date(),
      }
      setBusinessMessages((prev) => [...prev, aiMessage])
    } catch (error) {
      console.error("Error:", error)
      setBusinessMessages((prev) => [...prev, { id: (Date.now() + 1).toString(), content: `Error: ${error instanceof Error ? error.message : "Unknown error"}`, sender: "ai", timestamp: new Date() }])
    } finally {
      setIsBusinessLoading(false)
      void refreshTransparency()
    }
  }

  // Logistics chat handlers
  const handleLogisticsSend = async () => {
    if (!logisticsInput.trim() || !selectedLogistics) return

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      content: logisticsInput,
      sender: "user",
      timestamp: new Date(),
    }

    setLogisticsMessages((prev) => [...prev, userMessage])
    const message = logisticsInput
    setLogisticsInput("")
    setIsLogisticsLoading(true)

    try {
      let sid = logisticsSessionId.trim()
      if (!sid) {
        sid = crypto.randomUUID()
        setLogisticsSessionId(sid)
      }
      const response = await fetch(`${API_BASE}/api/v1/logistics/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          business_id: selectedLogistics.id,
          session_id: sid,
          sender: "logistics",
          message: message,
          api_key: apiKey || undefined,
        }),
      })

      const data = await response.json()
      const aiMessage: ChatMessage = {
        id: (Date.now() + 1).toString(),
        content: data.message || "No response",
        sender: "ai",
        timestamp: new Date(),
      }
      setLogisticsMessages((prev) => [...prev, aiMessage])
    } catch (error) {
      console.error("Error:", error)
      setLogisticsMessages((prev) => [...prev, { id: (Date.now() + 1).toString(), content: `Error: ${error instanceof Error ? error.message : "Unknown error"}`, sender: "ai", timestamp: new Date() }])
    } finally {
      setIsLogisticsLoading(false)
    }
  }

  // Analytics fetch helpers (shared by manual buttons and the background auto-refresh below)
  const fetchBusinessAnalytics = async (businessId: string) => {
    const response = await fetch(`${API_BASE}/api/v1/analytics/business`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ business_id: businessId, api_key: apiKey || undefined }),
    })
    return response.json()
  }

  const fetchUserAnalytics = async (userId: string) => {
    const response = await fetch(`${API_BASE}/api/v1/analytics/user`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, api_key: apiKey || undefined }),
    })
    return response.json()
  }

  const fetchInventoryReport = async (businessId: string) => {
    const response = await fetch(`${API_BASE}/api/v1/inventory/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ business_id: businessId, api_key: apiKey || undefined }),
    })
    return response.json()
  }

  const fetchSupplyChainReport = async (businessId: string) => {
    const response = await fetch(`${API_BASE}/api/v1/supply-chain/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ business_id: businessId, api_key: apiKey || undefined }),
    })
    return response.json()
  }

  // Manual "Get ..." button handlers — alert if the persona isn't picked yet, show the loading state.
  const handleBusinessAnalytics = async () => {
    if (!selectedBusiness) {
      alert("Please select a business first")
      return
    }
    setIsLoadingAnalytics(true)
    try {
      setBusinessAnalytics(await fetchBusinessAnalytics(selectedBusiness.id))
    } catch (error) {
      console.error("Error:", error)
    } finally {
      setIsLoadingAnalytics(false)
    }
  }

  const handleUserAnalytics = async () => {
    if (!selectedUser) {
      alert("Please select a user first")
      return
    }
    setIsLoadingAnalytics(true)
    try {
      setUserAnalytics(await fetchUserAnalytics(selectedUser.id))
    } catch (error) {
      console.error("Error:", error)
    } finally {
      setIsLoadingAnalytics(false)
    }
  }

  const handleInventoryManagement = async () => {
    if (!selectedBusiness) {
      alert("Please select a business first")
      return
    }
    setIsLoadingAnalytics(true)
    try {
      setInventoryData(await fetchInventoryReport(selectedBusiness.id))
    } catch (error) {
      console.error("Error:", error)
    } finally {
      setIsLoadingAnalytics(false)
    }
  }

  // Reports tab: once each report has been loaded once for the selected persona, keep it fresh
  // in the background (mirrors the sidebar's transparency-panel polling) without re-triggering
  // the loading spinner or the "please select a persona" alerts on every tick.
  useEffect(() => {
    if (workspaceTab !== "reports") return
    const tick = async () => {
      try {
        if (selectedBusiness) {
          if (businessAnalytics) setBusinessAnalytics(await fetchBusinessAnalytics(selectedBusiness.id))
          if (inventoryData) setInventoryData(await fetchInventoryReport(selectedBusiness.id))
          if (supplyChainData) setSupplyChainData(await fetchSupplyChainReport(selectedBusiness.id))
        }
        if (selectedUser && userAnalytics) {
          setUserAnalytics(await fetchUserAnalytics(selectedUser.id))
        }
      } catch (error) {
        console.error("Reports auto-refresh error:", error)
      }
    }
    const interval = setInterval(tick, TRANSPARENCY_POLL_MS)
    return () => clearInterval(interval)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceTab, selectedBusiness, selectedUser, apiKey])

  const handleClearRedisSession = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/session/clear`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: selectedUser?.id ?? null,
          vendor_id: selectedBusiness?.id ?? null,
          logistic_id: selectedLogistics?.id ?? null,
        }),
      })
      if (!res.ok) {
        const t = await res.text()
        throw new Error(t || res.statusText)
      }
      setCustomerMessages([
        {
          id: "welcome-customer",
          content: "Hello! Select a user and business to start chatting.",
          sender: "ai",
          timestamp: STATIC_WELCOME_TS,
        },
      ])
      setBusinessMessages([
        {
          id: "welcome-business",
          content: "Select a business to start chatting.",
          sender: "ai",
          timestamp: STATIC_WELCOME_TS,
        },
      ])
      setLogisticsMessages([
        {
          id: "welcome-logistics",
          content: "Logistics is linked automatically when you pick a business.",
          sender: "ai",
          timestamp: STATIC_WELCOME_TS,
        },
      ])
      setCustomerSessionId(crypto.randomUUID())
      setBusinessSessionId(crypto.randomUUID())
      setLogisticsSessionId(crypto.randomUUID())
      alert("Redis cleared for selected personas; chat panes reset.")
    } catch (e) {
      alert(`Clear session failed: ${e instanceof Error ? e.message : "Unknown error"}`)
    }
  }

  const handleSupplyChain = async () => {
    if (!selectedBusiness) {
      alert("Please select a business first")
      return
    }
    setIsLoadingAnalytics(true)
    try {
      const response = await fetch(`${API_BASE}/api/v1/supply-chain/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          business_id: selectedBusiness.id,
          api_key: apiKey || undefined,
        }),
      })
      const data = await response.json()
      setSupplyChainData(data)
    } catch (error) {
      console.error("Error:", error)
    } finally {
      setIsLoadingAnalytics(false)
    }
  }

  const canChat = !!(selectedUser && selectedBusiness)
  const hydrated = useHydrated()

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50">
      {/* Header */}
      <header className="bg-white shadow-lg border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex justify-between items-center">
            <div className="flex items-center space-x-3">
              <div className="flex items-center justify-center w-12 h-12 rounded-xl overflow-hidden bg-white">
                <img 
                  src="/ottobiz.png" 
                  alt="Ottobiz Logo" 
                  className="w-full h-full object-contain"
                />
              </div>
              <div>
                <h1 className="text-3xl font-bold bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">
                  Ottobiz
                </h1>
                <p className="text-sm text-gray-600">Automated Business Platform</p>
              </div>
            </div>
            <div className="flex items-center gap-2 flex-wrap justify-end">
              <Link
                href="/about"
                className="px-3 py-2 text-sm font-medium rounded-lg border border-gray-200 bg-white text-gray-700 hover:bg-gray-50 transition-colors"
              >
                About
              </Link>
              <Link
                href="/how-to-use"
                className="px-3 py-2 text-sm font-medium rounded-lg border border-gray-200 bg-white text-gray-700 hover:bg-gray-50 transition-colors"
              >
                How to use
              </Link>
              <button
                type="button"
                onClick={handleClearRedisSession}
                className="flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-lg border border-amber-300 bg-amber-50 text-amber-900 hover:bg-amber-100 transition-colors"
                title="Clears Redis state and inbox for selected user, business, and logistics personas"
              >
                <RotateCcw className="w-4 h-4" />
                Clear Redis session
              </button>

              {/* Currency selector */}
              <div className="bg-white rounded-lg px-2 py-2 border border-gray-200 flex items-center gap-1.5">
                <Coins className="w-4 h-4 text-gray-500 shrink-0" />
                <select
                  value={selectedCurrency}
                  onChange={(e) => setSelectedCurrency(e.target.value as CurrencyCode)}
                  className="text-sm border-none outline-none bg-transparent cursor-pointer pr-1"
                  title="Select display currency — prices are converted client-side"
                >
                  {CURRENCIES.map((c) => (
                    <option key={c.code} value={c.code}>
                      {c.symbol} {c.code} ({c.name})
                    </option>
                  ))}
                </select>
              </div>

              <div className="bg-white rounded-lg p-2 border border-gray-200">
                <div className="flex items-center space-x-2">
                  <Key className="w-4 h-4 text-gray-500" />
                  <input
                    type="password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder="API Key (optional)"
                    className="text-sm border-none outline-none w-32"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
        {/* Persona Selection */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
          {/* User Persona */}
          <div className="bg-white rounded-lg shadow-md p-3">
            <div className="flex items-center space-x-2 mb-2">
              <Users className="w-5 h-5 text-blue-600" />
              <h3 className="text-sm font-semibold text-gray-800">User Persona</h3>
            </div>
            <div className="grid grid-cols-2 gap-2 max-h-28 overflow-y-auto">
              {predefinedUsers.map((user) => (
                <button
                  key={user.id}
                  onClick={() => { setSelectedUser(user); setCustomerSessionId(crypto.randomUUID()) }}
                  className={`p-2 rounded text-sm transition-all ${
                    selectedUser?.id === user.id
                      ? "bg-blue-500 text-white"
                      : "bg-gray-100 hover:bg-gray-200"
                  }`}
                >
                  {user.name}
                </button>
              ))}
            </div>
          </div>

          {/* Business Persona */}
          <div className="bg-white rounded-lg shadow-md p-3">
            <div className="flex items-center space-x-2 mb-2">
              <Building2 className="w-5 h-5 text-green-600" />
              <h3 className="text-sm font-semibold text-gray-800">Business Persona</h3>
            </div>
            <div className="grid grid-cols-2 gap-2 max-h-28 overflow-y-auto">
              {predefinedBusinesses.map((business) => (
                <button
                  key={business.id}
                  onClick={() => { setSelectedBusiness(business); setBusinessSessionId(crypto.randomUUID()); setCustomerSessionId(crypto.randomUUID()) }}
                  className={`p-2 rounded text-sm transition-all ${
                    selectedBusiness?.id === business.id
                      ? "bg-green-500 text-white"
                      : "bg-gray-100 hover:bg-gray-200"
                  }`}
                >
                  {business.name}
                </button>
              ))}
            </div>
          </div>

          {/* Linked logistics (auto from backend when a business is selected) */}
          <div className="bg-white rounded-lg shadow-md p-3">
            <div className="flex items-center space-x-2 mb-2">
              <Truck className="w-5 h-5 text-orange-600" />
              <h3 className="text-sm font-semibold text-gray-800">Linked logistics</h3>
            </div>
            <p className="text-[11px] text-gray-500 mb-2 leading-snug">
              DB partner when configured; otherwise a random registered carrier for simulation.
            </p>
            <div className="grid grid-cols-2 gap-2 max-h-28 overflow-y-auto">
              {predefinedLogistics.map((logistics) => (
                <div
                  key={logistics.id}
                  className={`p-2 rounded text-sm ${
                    selectedLogistics?.id === logistics.id
                      ? "bg-orange-500 text-white"
                      : "bg-gray-100 text-gray-600"
                  }`}
                >
                  {logistics.name}
                </div>
              ))}
            </div>
          </div>
        </div>

        <div
          className="flex flex-wrap items-center gap-2 mb-3 border-b border-gray-200 pb-2"
          role="tablist"
          aria-label="Workspace"
        >
          <button
            type="button"
            role="tab"
            aria-selected={workspaceTab === "chats"}
            onClick={() => setWorkspaceTab("chats")}
            className={`rounded-full px-4 py-1.5 text-sm font-medium transition-colors ${
              workspaceTab === "chats"
                ? "bg-blue-600 text-white shadow-sm"
                : "bg-gray-100 text-gray-700 hover:bg-gray-200"
            }`}
          >
            Chats & session
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={workspaceTab === "reports"}
            onClick={() => setWorkspaceTab("reports")}
            className={`rounded-full px-4 py-1.5 text-sm font-medium transition-colors ${
              workspaceTab === "reports"
                ? "bg-purple-600 text-white shadow-sm"
                : "bg-gray-100 text-gray-700 hover:bg-gray-200"
            }`}
          >
            Reports & data
          </button>
          <span className="text-xs text-gray-500 ml-auto hidden sm:inline">
            {workspaceTab === "chats"
              ? "Three chat panes + catalog / orders / agent state"
              : "Business & user analytics, inventory, supply chain"}
          </span>
        </div>

        {workspaceTab === "chats" ? (
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
          {/* Customer Chat */}
          <div className="bg-white rounded-lg shadow-xl border border-gray-200 min-h-[20rem] h-[min(28rem,52vh)] flex flex-col">
            <div className="bg-blue-500 text-white p-3 rounded-t-lg flex items-center space-x-2">
              <User className="w-5 h-5" />
              <h3 className="font-semibold">Customer Chat</h3>
            </div>
            <div ref={customerChatScrollRef} className="flex-1 overflow-y-auto overscroll-contain p-4 space-y-2">
              {customerMessages.map((msg) => (
                <div
                  key={msg.id}
                  className={`flex ${msg.sender === "user" ? "justify-end" : "justify-start"}`}
                >
                  <div
                    className={`max-w-[80%] px-3 py-2 rounded-lg text-sm ${
                      msg.sender === "user"
                        ? "bg-blue-500 text-white"
                        : "bg-gray-100 text-gray-800"
                    }`}
                  >
                    <ChatMessageBody
                      content={rewriteTextCurrency(msg.content, selectedCurrency)}
                      invert={msg.sender === "user"}
                    />
                  </div>
                  </div>
                ))}
              {isCustomerLoading && (
                  <div className="flex justify-start">
                  <div className="bg-gray-100 px-3 py-2 rounded-lg text-sm">Thinking...</div>
                  </div>
                )}
            </div>
            {/* File Preview */}
            {selectedFiles.length > 0 && (
              <div className="px-4 pb-2">
                <div className="flex flex-wrap gap-2">
                  {selectedFiles.map((file, index) => (
                    <div key={index} className="flex items-center space-x-2 bg-gray-100 rounded-lg px-2 py-1 text-xs">
                      {file.type.startsWith("image/") ? (
                        <ImageIcon className="w-3 h-3" />
                      ) : file.type === "application/pdf" ? (
                        <FileText className="w-3 h-3" />
                      ) : (
                        <Volume2 className="w-3 h-3" />
                      )}
                      <span className="truncate max-w-24">{file.name}</span>
                      <button
                        type="button"
                        onClick={() => removeFile(index)}
                        className="text-red-500 hover:text-red-700"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}
            <div className="border-t p-3">
              <div className="flex space-x-2">
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="p-2 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded transition-colors"
                  disabled={!hydrated || !canChat}
                >
                  <Paperclip className="w-4 h-4" />
                </button>
                <input
                  type="text"
                  value={customerInput}
                  onChange={(e) => setCustomerInput(e.target.value)}
                  onFocus={holdScrollPosition}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault()
                      holdScrollPosition()
                      void handleCustomerSend()
                    }
                  }}
                  placeholder={canChat ? "Type a message..." : "Select user & business first"}
                  className="flex-1 border rounded px-3 py-2 text-sm"
                  disabled={!hydrated || !canChat || isCustomerLoading}
                />
                <button
                  type="button"
                  onClick={handleCustomerSend}
                  disabled={
                    !hydrated ||
                    !canChat ||
                    isCustomerLoading ||
                    (!customerInput.trim() && selectedFiles.length === 0)
                  }
                  className="bg-blue-500 text-white px-4 py-2 rounded disabled:opacity-50"
                >
                  <Send className="w-4 h-4" />
                </button>
              </div>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept="image/*,audio/*,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/*,.pdf,.doc,.docx,.txt,.xls,.xlsx"
              onChange={handleFileSelect}
              className="hidden"
            />
              </div>

          {/* Business Chat */}
          <div className="bg-white rounded-lg shadow-xl border border-gray-200 min-h-[20rem] h-[min(28rem,52vh)] flex flex-col">
            <div className="bg-green-500 text-white p-3 rounded-t-lg flex items-center space-x-2">
              <Building2 className="w-5 h-5" />
              <h3 className="font-semibold">Business Chat</h3>
            </div>
            <div ref={businessChatScrollRef} className="flex-1 overflow-y-auto overscroll-contain p-4 space-y-2">
              {businessMessages.map((msg) => (
                <div
                  key={msg.id}
                  className={`flex ${msg.sender === "user" ? "justify-end" : "justify-start"}`}
                >
                  <div
                    className={`max-w-[80%] px-3 py-2 rounded-lg text-sm ${
                      msg.sender === "user"
                        ? "bg-green-500 text-white"
                        : "bg-gray-100 text-gray-800"
                    }`}
                  >
                    <ChatMessageBody
                      content={rewriteTextCurrency(msg.content, selectedCurrency)}
                      invert={msg.sender === "user"}
                    />
                  </div>
                </div>
              ))}
              {isBusinessLoading && (
                <div className="flex justify-start">
                  <div className="bg-gray-100 px-3 py-2 rounded-lg text-sm">Thinking...</div>
                </div>
              )}
            </div>
            <div className="border-t p-3">
              <div className="flex space-x-2">
                  <input
                    type="text"
                  value={businessInput}
                  onChange={(e) => setBusinessInput(e.target.value)}
                  onFocus={holdScrollPosition}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault()
                      holdScrollPosition()
                      void handleBusinessSend()
                    }
                  }}
                  placeholder={selectedBusiness ? "Type a message..." : "Select business first"}
                  className="flex-1 border rounded px-3 py-2 text-sm"
                  disabled={!hydrated || !selectedBusiness || isBusinessLoading}
                  />
                  <button
                  onClick={handleBusinessSend}
                  disabled={!hydrated || !selectedBusiness || isBusinessLoading}
                  className="bg-green-500 text-white px-4 py-2 rounded disabled:opacity-50"
                >
                  <Send className="w-4 h-4" />
                  </button>
              </div>
            </div>
          </div>

          {/* Logistics Chat */}
          <div className="bg-white rounded-lg shadow-xl border border-gray-200 min-h-[20rem] h-[min(28rem,52vh)] flex flex-col">
            <div className="bg-orange-500 text-white p-3 rounded-t-lg flex items-center space-x-2">
              <Truck className="w-5 h-5" />
              <h3 className="font-semibold">Logistics Chat</h3>
            </div>
            <div ref={logisticsChatScrollRef} className="flex-1 overflow-y-auto overscroll-contain p-4 space-y-2">
              {logisticsMessages.map((msg) => (
                <div
                  key={msg.id}
                  className={`flex ${msg.sender === "user" ? "justify-end" : "justify-start"}`}
                >
                  <div
                    className={`max-w-[80%] px-3 py-2 rounded-lg text-sm ${
                      msg.sender === "user"
                        ? "bg-orange-500 text-white"
                        : "bg-gray-100 text-gray-800"
                    }`}
                  >
                    <ChatMessageBody
                      content={rewriteTextCurrency(msg.content, selectedCurrency)}
                      invert={msg.sender === "user"}
                    />
                  </div>
                </div>
              ))}
              {isLogisticsLoading && (
                <div className="flex justify-start">
                  <div className="bg-gray-100 px-3 py-2 rounded-lg text-sm">Thinking...</div>
              </div>
              )}
            </div>
            <div className="border-t p-3">
              <div className="flex space-x-2">
                <input
                  type="text"
                  value={logisticsInput}
                  onChange={(e) => setLogisticsInput(e.target.value)}
                  onFocus={holdScrollPosition}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault()
                      holdScrollPosition()
                      void handleLogisticsSend()
                    }
                  }}
                  placeholder={selectedLogistics ? "Type a message..." : "Select logistics first"}
                  className="flex-1 border rounded px-3 py-2 text-sm"
                  disabled={!hydrated || !selectedLogistics || isLogisticsLoading}
                />
                <button
                  onClick={handleLogisticsSend}
                  disabled={!hydrated || !selectedLogistics || isLogisticsLoading}
                  className="bg-orange-500 text-white px-4 py-2 rounded disabled:opacity-50"
                >
                  <Send className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>
          </div>

          {selectedBusiness ? (
            <>
              <p className="text-[10px] text-gray-500 flex items-center gap-1.5 px-0.5">
                {transparencyRefreshing ? (
                  <RefreshCw className="w-3 h-3 shrink-0 animate-spin text-indigo-600" />
                ) : null}
                {transparencyFetchError ? (
                  <span className="text-amber-700">{transparencyFetchError}</span>
                ) : transparencyUpdatedAt ? (
                  <span>
                    Last sync {transparencyUpdatedAt.toLocaleTimeString()} · auto every{" "}
                    {TRANSPARENCY_POLL_MS / 1000}s
                  </span>
                ) : (
                  <span>Syncing panels…</span>
                )}
              </p>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div className="bg-white rounded-lg shadow-md border border-gray-200 p-3">
                  <div className="flex items-center justify-between gap-2 mb-2">
                    <h4 className="text-sm font-semibold text-gray-800 flex items-center gap-1">
                      <Package className="w-4 h-4 text-green-600" />
                      Catalog (top 15)
                    </h4>
                    <button
                      type="button"
                      disabled={!hydrated}
                      onClick={() => void refreshTransparency()}
                      className="text-xs px-2 py-1 rounded border border-gray-300 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      Refresh
                    </button>
                  </div>
                  <p className="text-[10px] text-gray-400 mb-1">
                    DB snapshot · auto every {TRANSPARENCY_POLL_MS / 1000}s
                  </p>
                  <div className="max-h-52 overflow-y-auto overscroll-contain text-xs">
                    <table className="w-full text-left border-collapse">
                      <thead>
                        <tr className="text-gray-500 border-b">
                          <th className="py-1 pr-1 font-medium">Product</th>
                          <th className="py-1 pr-1 font-medium">Price</th>
                          <th className="py-1 font-medium">Qty</th>
                        </tr>
                      </thead>
                      <tbody>
                        {topProducts.length === 0 ? (
                          <tr>
                            <td colSpan={3} className="py-2 text-gray-400">
                              No products
                            </td>
                          </tr>
                        ) : (
                          topProducts.map((p) => (
                            <tr key={p.id || p.name} className="border-b border-gray-100">
                              <td
                                className="py-1 pr-1 truncate max-w-[8rem]"
                                title={p.name ?? ""}
                              >
                                {p.name ?? "—"}
                              </td>
                              <td className="py-1 pr-1 whitespace-nowrap">
                                {formatAmount(p.price, p.currency, selectedCurrency)}
                              </td>
                              <td className="py-1">{p.stock_quantity}</td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div className="bg-white rounded-lg shadow-md border border-gray-200 overflow-hidden flex flex-col min-h-0">
                  <div className="flex items-stretch shrink-0 border-b border-gray-100 bg-gray-50">
                    <div className="flex-1 flex items-center px-3 py-2 text-sm font-medium text-gray-800 text-left min-w-0">
                      <span className="truncate flex items-center gap-1">
                        <ShoppingCart className="w-4 h-4 shrink-0 text-indigo-600" />
                        Active orders (DB)
                      </span>
                    </div>
                    <button
                      type="button"
                      title="Refresh catalog, orders, and session panels"
                      disabled={!hydrated}
                      onClick={() => void refreshTransparency()}
                      className="px-2.5 border-l border-gray-200 text-gray-600 hover:text-indigo-700 hover:bg-indigo-50 disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      <RefreshCw
                        className={`w-4 h-4 ${transparencyRefreshing ? "animate-spin" : ""}`}
                      />
                    </button>
                  </div>
                  <div className="p-3 min-h-[10rem] max-h-72 overflow-y-auto overscroll-contain text-xs border-t border-gray-100 space-y-2">
                    <p className="text-[10px] text-gray-400">
                      Non-terminal orders · needs user + business · auto every {TRANSPARENCY_POLL_MS / 1000}s
                    </p>
                    {!canChat ? (
                      <p className="text-gray-400">Select user and business</p>
                    ) : activeSessionOrders.length === 0 ? (
                      <p className="text-gray-400">No active orders for this pair</p>
                    ) : (
                      activeSessionOrders.map((ord) => {
                        const qty = sessionOrderQtyHint(ord)
                        const addr = [ord.delivery_address, ord.delivery_city, ord.delivery_state]
                          .filter(Boolean)
                          .join(", ")
                        return (
                          <div
                            key={ord.id}
                            className="border border-indigo-100 rounded-md p-2 bg-indigo-50/40 text-gray-800"
                          >
                            <div className="font-semibold text-indigo-900">
                              {ord.order_number ?? ord.id.slice(0, 8)}
                              <span className="font-normal text-gray-600 ml-2">
                                · {ord.status ?? "—"}
                              </span>
                            </div>
                            {ord.product_name ? (
                              <div className="mt-0.5">
                                <span className="text-gray-500">product</span> {ord.product_name}
                              </div>
                            ) : null}
                            <div className="mt-0.5 text-gray-700">
                              <span className="text-gray-500">total</span>{" "}
                              {ord.total_amount != null ? formatAmount(ord.total_amount, "NGN", selectedCurrency) : "—"}
                              {qty ? (
                                <>
                                  {" "}
                                  · <span className="text-gray-500">qty</span> {qty}
                                </>
                              ) : null}
                            </div>
                            <div className="font-mono text-[10px] text-gray-500 mt-0.5 break-all">
                              id {ord.id}
                            </div>
                            {ord.tracking_number ? (
                              <div>
                                <span className="text-gray-500">tracking</span> {ord.tracking_number}
                              </div>
                            ) : null}
                            {ord.logistic_id ? (
                              <div className="text-[10px]">
                                <span className="text-gray-500">logistics</span> {ord.logistic_id}
                              </div>
                            ) : null}
                            {addr ? (
                              <div className="text-gray-600 mt-0.5 line-clamp-2" title={addr}>
                                {addr}
                              </div>
                            ) : null}
                            {ord.updated_at ? (
                              <div className="text-[10px] text-gray-400 mt-1">updated {ord.updated_at}</div>
                            ) : null}
                          </div>
                        )
                      })
                    )}
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                <div className="bg-white rounded-lg shadow-md border border-gray-200 overflow-hidden flex flex-col min-h-0">
                  <div className="flex items-stretch shrink-0 border-b border-gray-100 bg-gray-50">
                    <div className="flex-1 flex items-center px-3 py-2 text-sm font-medium text-gray-800 text-left min-w-0">
                      <span className="truncate">Products discussed (session)</span>
                    </div>
                    <button
                      type="button"
                      title="Refresh from Redis (products discussed + processes)"
                      disabled={!hydrated}
                      onClick={() => void refreshSessionPanels()}
                      className="px-2.5 border-l border-gray-200 text-gray-600 hover:text-blue-600 hover:bg-blue-50 disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      <RefreshCw
                        className={`w-4 h-4 ${transparencyRefreshing ? "animate-spin" : ""}`}
                      />
                    </button>
                  </div>
                  <div className="p-3 flex-1 min-h-[10rem] max-h-64 overflow-y-auto overscroll-contain text-xs border-t border-gray-100">
                      {!canChat ? (
                        <p className="text-gray-400">Select user and business</p>
                      ) : agentProducts.length === 0 ? (
                        <p className="text-gray-400">None in session yet — chat about a product (Redis user:vendor)</p>
                      ) : (
                        <ul className="space-y-2">
                          {agentProducts.map((p, i) => (
                            <li
                              key={`${p.cache_key ?? ""}-${p.id ?? ""}-${i}`}
                              className="border-b border-gray-50 pb-1 last:border-0"
                            >
                              <div className="font-medium text-gray-800">
                                {p.name ?? p.id ?? "—"}
                              </div>
                              <div className="text-gray-500">
                                {p.price != null && Number(p.price) > 0
                                  ? formatAmount(p.price, p.currency, selectedCurrency)
                                  : "—"}{" "}
                                · stock {p.stock_quantity ?? "—"}
                              </div>
                            </li>
                          ))}
                        </ul>
                      )}
                  </div>
                </div>

                <div className="bg-white rounded-lg shadow-md border border-gray-200 overflow-hidden flex flex-col max-h-[26rem] min-h-0">
                  <div className="flex items-stretch shrink-0 border-b border-gray-100 bg-gray-50">
                    <div className="flex-1 flex items-center px-3 py-2 text-sm font-medium text-gray-800 text-left min-w-0">
                      <span className="truncate">Processes (session)</span>
                    </div>
                    <button
                      type="button"
                      title="Refresh from Redis (products discussed + processes)"
                      disabled={!hydrated}
                      onClick={() => void refreshSessionPanels()}
                      className="px-2.5 border-l border-gray-200 text-gray-600 hover:text-blue-600 hover:bg-blue-50 disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      <RefreshCw
                        className={`w-4 h-4 ${transparencyRefreshing ? "animate-spin" : ""}`}
                      />
                    </button>
                  </div>
                  <div className="p-3 flex-1 min-h-[12rem] max-h-72 overflow-y-auto overscroll-contain text-xs border-t border-gray-100 space-y-2">
                      <p className="text-[10px] text-gray-400 shrink-0">
                        Redis session processes · auto every {TRANSPARENCY_POLL_MS / 1000}s and after chat
                      </p>
                      {!canChat ? (
                        <p className="text-gray-400">Select user and business</p>
                      ) : agentProcesses.length === 0 ? (
                        <p className="text-gray-400">No processes</p>
                      ) : (
                        agentProcesses.map((pr) => (
                          <div
                            key={pr.process_id}
                            className="border border-gray-100 rounded-md p-2 bg-gray-50/90 text-gray-800"
                          >
                            <div className="font-mono text-[11px] break-all" title={pr.process_id}>
                              {pr.process_id}
                            </div>
                            <div>
                              <span className="text-gray-500">task</span>{" "}
                              {pr.task_type ?? "—"}
                            </div>
                            <div>
                              <span className="text-gray-500">product</span>{" "}
                              {pr.product_name ?? "—"}
                            </div>
                            <div>
                              <span className="text-gray-500">order</span>{" "}
                              {pr.order_number ?? pr.order_id ?? "—"}
                            </div>
                            <div>
                              <span className="text-gray-500">status</span> {pr.status ?? "—"} ·{" "}
                              <span className="text-gray-500">qty</span>{" "}
                              {pr.quantity ?? "—"}
                            </div>
                            {pr.tracking_number ? (
                              <div>
                                <span className="text-gray-500">tracking</span>{" "}
                                {pr.tracking_number}
                              </div>
                            ) : null}
                            {pr.completed ? (
                              <div className="text-green-600 font-medium">completed</div>
                            ) : null}
                          </div>
                        ))
                      )}
                  </div>
                </div>

                <div className="bg-white rounded-lg shadow-md border border-gray-200 overflow-hidden flex flex-col max-h-[22rem] min-h-0">
                  <div className="flex items-stretch shrink-0 border-b border-gray-100 bg-gray-50">
                    <button
                      type="button"
                      className="flex-1 flex items-center justify-between px-3 py-2 text-sm font-medium text-gray-800 hover:bg-gray-100 text-left min-w-0"
                      onClick={() => setSbInventoryActivityOpen((v) => !v)}
                    >
                      <span className="truncate">Inventory updates (agents)</span>
                      {sbInventoryActivityOpen ? (
                        <ChevronDown className="w-4 h-4 shrink-0 ml-1" />
                      ) : (
                        <ChevronRight className="w-4 h-4 shrink-0 ml-1" />
                      )}
                    </button>
                    <button
                      type="button"
                      title="Refresh catalog & inventory activity"
                      disabled={!hydrated}
                      onClick={() => void refreshTransparency()}
                      className="px-2.5 border-l border-gray-200 text-gray-600 hover:text-emerald-700 hover:bg-emerald-50 disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      <RefreshCw
                        className={`w-4 h-4 ${transparencyRefreshing ? "animate-spin" : ""}`}
                      />
                    </button>
                  </div>
                  {sbInventoryActivityOpen && (
                    <div className="p-3 flex-1 min-h-[10rem] max-h-64 overflow-y-auto overscroll-contain text-xs border-t border-gray-100 space-y-2">
                      <p className="text-[10px] text-gray-400">
                        Stock / price / new products from agent tools · same interval as catalog
                      </p>
                      {inventoryActivity.length === 0 ? (
                        <p className="text-gray-400">No mutations logged yet (try a stock or price update in chat)</p>
                      ) : (
                        <ul className="space-y-2">
                          {inventoryActivity.map((ev, idx) => {
                            const t = ev.at
                              ? new Date(ev.at).toLocaleString(undefined, {
                                  month: "short",
                                  day: "numeric",
                                  hour: "2-digit",
                                  minute: "2-digit",
                                })
                              : "—"
                            const kind =
                              ev.kind === "stock"
                                ? "Stock"
                                : ev.kind === "price"
                                  ? "Price"
                                  : ev.kind === "add"
                                    ? "New product"
                                    : ev.kind ?? "Update"
                            return (
                              <li
                                key={`${ev.product_id ?? idx}-${ev.at ?? idx}`}
                                className="border border-gray-100 rounded-md p-2 bg-emerald-50/40 text-gray-800"
                              >
                                <div className="flex justify-between gap-2 text-[10px] text-gray-500">
                                  <span className="font-medium text-emerald-800">{kind}</span>
                                  <span>{t}</span>
                                </div>
                                <div className="font-medium mt-0.5">{ev.name ?? ev.product_id ?? "—"}</div>
                                <div className="text-gray-600 mt-0.5">
                                  {ev.kind === "add"
                                    ? `${ev.price != null ? formatAmount(ev.price, ev.currency, selectedCurrency) : "—"} · Qty ${ev.stock_quantity ?? "—"}`
                                    : ev.kind === "price"
                                      ? `Price ${ev.price != null ? formatAmount(ev.price, ev.currency, selectedCurrency) : "—"}`
                                      : ev.kind === "stock"
                                        ? `Stock qty ${ev.stock_quantity ?? "—"}`
                                        : [
                                            ev.price != null
                                              ? formatAmount(ev.price, ev.currency, selectedCurrency)
                                              : null,
                                            ev.stock_quantity != null ? `Qty ${ev.stock_quantity}` : null,
                                          ]
                                            .filter(Boolean)
                                            .join(" · ") || "—"}
                                </div>
                              </li>
                            )
                          })}
                        </ul>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className="bg-white rounded-lg shadow border border-dashed border-gray-200 p-4 text-sm text-gray-500">
              Select a business to load catalog and session debug panels.
            </div>
          )}
        </div>
        ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
          {/* Business Analytics */}
          <div className="bg-white rounded-lg shadow-md p-3">
              <div className="flex items-center space-x-2 mb-2">
              <BarChart3 className="w-5 h-5 text-purple-600" />
              <h3 className="font-semibold text-gray-800">Business Analytics</h3>
              </div>
              <button
              onClick={handleBusinessAnalytics}
              disabled={!hydrated || !selectedBusiness || isLoadingAnalytics}
              className="w-full bg-purple-500 text-white py-1.5 text-sm rounded disabled:opacity-50 mb-2"
            >
              Get Analytics
              </button>
            {businessAnalytics && (
              <div className="bg-gray-50 rounded p-2 text-xs max-h-32 overflow-y-auto">
                <pre>{JSON.stringify(businessAnalytics, null, 2)}</pre>
                </div>
              )}
            </div>

            {/* User Analytics */}
          <div className="bg-white rounded-lg shadow-md p-3">
              <div className="flex items-center space-x-2 mb-2">
              <TrendingUp className="w-5 h-5 text-blue-600" />
              <h3 className="font-semibold text-gray-800">User Analytics</h3>
            </div>
            <button
              onClick={handleUserAnalytics}
              disabled={!hydrated || !selectedUser || isLoadingAnalytics}
              className="w-full bg-blue-500 text-white py-1.5 text-sm rounded disabled:opacity-50 mb-2"
            >
              Get Analytics
            </button>
            {userAnalytics && (
              <div className="bg-gray-50 rounded p-2 text-xs max-h-32 overflow-y-auto">
                <pre>{JSON.stringify(userAnalytics, null, 2)}</pre>
              </div>
            )}
          </div>

          {/* Inventory Management */}
          <div className="bg-white rounded-lg shadow-md p-3">
            <div className="flex items-center space-x-2 mb-2">
              <Package className="w-5 h-5 text-green-600" />
              <h3 className="font-semibold text-gray-800">Inventory</h3>
              </div>
              <button
              onClick={handleInventoryManagement}
              disabled={!hydrated || !selectedBusiness || isLoadingAnalytics}
              className="w-full bg-green-500 text-white py-1.5 text-sm rounded disabled:opacity-50 mb-2"
            >
              Get Inventory
              </button>
            {inventoryData && (
              <div className="bg-gray-50 rounded p-2 text-xs max-h-32 overflow-y-auto">
                <pre>{JSON.stringify(inventoryData, null, 2)}</pre>
                </div>
              )}
          </div>

          {/* Supply Chain */}
          <div className="bg-white rounded-lg shadow-md p-3">
            <div className="flex items-center space-x-2 mb-2">
              <Truck className="w-5 h-5 text-orange-600" />
              <h3 className="font-semibold text-gray-800">Supply Chain</h3>
            </div>
            <button
              onClick={handleSupplyChain}
              disabled={!hydrated || !selectedBusiness || isLoadingAnalytics}
              className="w-full bg-orange-500 text-white py-1.5 text-sm rounded disabled:opacity-50 mb-2"
            >
              Get Supply Chain
            </button>
            {supplyChainData && (
              <div className="bg-gray-50 rounded p-2 text-xs max-h-32 overflow-y-auto">
                <pre>{JSON.stringify(supplyChainData, null, 2)}</pre>
              </div>
            )}
          </div>
        </div>
        )}
      </div>
    </div>
  )
}
