/** @type {import('next').NextConfig} */

// NEXT_PUBLIC_BACKEND_URL is inlined into the JS bundle at build time by Next.js.
// BACKEND_URL is a server-side-only variable read at build time here in next.config.mjs.
// In production (Docker/Coolify) set NEXT_PUBLIC_BACKEND_URL as a build-time env var
// so both the rewrite proxy and the browser bundle point at the real backend.
const backendTarget = (
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  process.env.BACKEND_URL ||
  "http://localhost:8000"
).replace(/\/$/, "")

const nextConfig = {
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    remotePatterns: [
      { protocol: "http", hostname: "localhost" },
    ],
    unoptimized: true,
  },
  async rewrites() {
    return [
      {
        source: "/backend/:path*",
        destination: `${backendTarget}/:path*`,
      },
    ]
  },
}

export default nextConfig
