import { NextResponse } from "next/server"

export async function GET() {
  const backendUrl = (
    process.env.BACKEND_URL ||
    process.env.NEXT_PUBLIC_BACKEND_URL ||
    "https://ottobiz-backend-zg2fve-56544e-212-47-72-183.sslip.io"
  ).replace(/\/$/, "")

  let probeStatus: string
  if (!backendUrl) {
    probeStatus = "SKIPPED — no backend URL configured (set BACKEND_URL or NEXT_PUBLIC_BACKEND_URL)"
  } else {
    try {
      const res = await fetch(`${backendUrl}/`, {
        signal: AbortSignal.timeout(5000),
      })
      probeStatus = `${res.status} ${res.statusText}`
    } catch (err: unknown) {
      probeStatus = `FAILED — ${err instanceof Error ? err.message : String(err)}`
    }
  }

  return NextResponse.json({
    BACKEND_URL: process.env.BACKEND_URL ?? "(not set)",
    NEXT_PUBLIC_BACKEND_URL: process.env.NEXT_PUBLIC_BACKEND_URL ?? "(not set)",
    window_BACKEND_URL: "(injected at runtime by layout.tsx — check browser console)",
    resolved_for_server: backendUrl || "(not set — configure BACKEND_URL or NEXT_PUBLIC_BACKEND_URL)",
    backend_probe: probeStatus,
  })
}
