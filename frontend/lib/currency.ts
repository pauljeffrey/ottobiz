export const CURRENCIES = [
  { code: "NGN", symbol: "₦", name: "Nigerian Naira" },
  { code: "USD", symbol: "$",  name: "US Dollar" },
  { code: "CAD", symbol: "C$", name: "Canadian Dollar" },
  { code: "AUD", symbol: "A$", name: "Australian Dollar" },
  { code: "GBP", symbol: "£",  name: "British Pound" },
  { code: "EUR", symbol: "€",  name: "Euro" },
  { code: "ZAR", symbol: "R",  name: "South African Rand" },
] as const

export type CurrencyCode = (typeof CURRENCIES)[number]["code"]

/**
 * Approximate mid-market rates relative to USD (1 USD = X units of each currency).
 * Update these periodically for demo accuracy.
 */
const RATES_VS_USD: Record<CurrencyCode, number> = {
  USD: 1.00,
  CAD: 1.38,
  AUD: 1.56,
  NGN: 1600,
  GBP: 0.79,
  EUR: 0.93,
  ZAR: 18.4,
}

/** Convert an amount from one currency to another. Falls back to NGN when source is unknown. */
export function convertAmount(
  amount: number,
  fromCode: string | null | undefined,
  toCode: CurrencyCode,
): number {
  const from = (fromCode?.toUpperCase().trim() ?? "NGN") as CurrencyCode
  if (from === toCode) return amount
  const fromRate = RATES_VS_USD[from] ?? RATES_VS_USD.NGN
  const toRate = RATES_VS_USD[toCode]
  return (amount / fromRate) * toRate
}

/** Format a price with the target currency symbol. Returns "—" for null/undefined. */
export function formatAmount(
  amount: number | null | undefined,
  fromCode: string | null | undefined,
  toCode: CurrencyCode,
): string {
  if (amount == null || isNaN(Number(amount))) return "—"
  const converted = convertAmount(Number(amount), fromCode, toCode)
  const entry = CURRENCIES.find((c) => c.code === toCode)
  return `${entry?.symbol ?? toCode} ${converted.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function parseMoneyNumber(raw: string): number {
  return parseFloat(raw.replace(/,/g, ""))
}

/** Rewrite NGN/naira amounts in agent chat text for the selected display currency. */
export function rewriteTextCurrency(text: string, toCode: CurrencyCode): string {
  if (!text || toCode === "NGN") return text

  let out = text

  out = out.replace(/₦\s*([\d,]+(?:\.\d{1,2})?)/g, (_, num) =>
    formatAmount(parseMoneyNumber(num), "NGN", toCode),
  )
  out = out.replace(/\bNGN\s*([\d,]+(?:\.\d{1,2})?)/gi, (_, num) =>
    formatAmount(parseMoneyNumber(num), "NGN", toCode),
  )
  out = out.replace(/\b([\d,]+(?:\.\d{1,2})?)\s*naira\b/gi, (_, num) =>
    formatAmount(parseMoneyNumber(num), "NGN", toCode),
  )

  return out
}
