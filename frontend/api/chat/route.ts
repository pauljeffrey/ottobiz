import { type NextRequest, NextResponse } from "next/server"

export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData()

    // Get the backend URL from environment variables — no fallback, must be explicitly configured
    const backendUrl = (
      process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || "https://ottobiz-backend-zg2fve-56544e-212-47-72-183.sslip.io"
    ).replace(/\/$/, "")

    if (!backendUrl) {
      return NextResponse.json(
        { error: "Backend URL is not configured. Set BACKEND_URL or NEXT_PUBLIC_BACKEND_URL." },
        { status: 503 }
      )
    }

    // Forward the request to your Python backend
    const response = await fetch(`${backendUrl}/chat`, {
      method: "POST",
      body: formData,
    })

    if (!response.ok) {
      throw new Error(`Backend responded with status: ${response.status}`)
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error("Error forwarding request to backend:", error)
    return NextResponse.json({ error: "Failed to process request" }, { status: 500 })
  }
}
