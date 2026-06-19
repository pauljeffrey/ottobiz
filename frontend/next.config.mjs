/** @type {import('next').NextConfig} */

// NEXT_PUBLIC_BACKEND_URL is inlined into the JS bundle at build time by Next.js.
// BACKEND_URL is a server-side-only variable used here as a fallback for the rewrite proxy.
// At least one of these must be set in production — the app will not proxy correctly without them.
const backendTarget = (
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  process.env.BACKEND_URL ||
  ""
).replace(/\/$/, "")

if (!backendTarget) {
  console.error(
    "ERROR: Neither NEXT_PUBLIC_BACKEND_URL nor BACKEND_URL is set. " +
    "The /backend rewrite proxy will be inactive. " +
    "Set one of these environment variables before building or starting the server."
  )
}

const nextConfig = {
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
  async rewrites() {
    if (!backendTarget) return []
    return [
      {
        source: "/backend/:path*",
        destination: `${backendTarget}/:path*`,
      },
    ]
  },
}

export default nextConfig
