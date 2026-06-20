import type React from "react"
import type { Metadata } from "next"
import { Inter } from "next/font/google"
import "./globals.css"

const inter = Inter({ subsets: ["latin"] })

export const metadata: Metadata = {
  title: "Ottobiz - Automated Business Platform",
  description: "AI-powered automated business platform for customers, businesses, and logistics",
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  // Read server-side env var at request time (not build time) and inject it
  // into window.__BACKEND_URL__ so the client bundle can use it directly
  // without relying on NEXT_PUBLIC_* build-time baking or a proxy rewrite.
  const backendUrl = (
    process.env.BACKEND_URL ||
    process.env.NEXT_PUBLIC_BACKEND_URL ||
    "https://ottobiz-backend-zg2fve-56544e-212-47-72-183.sslip.io"
  ).replace(/\/$/, "")

  return (
    <html lang="en">
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `window.__BACKEND_URL__=${JSON.stringify(backendUrl)};`,
          }}
        />
      </head>
      <body className={inter.className}>{children}</body>
    </html>
  )
}
