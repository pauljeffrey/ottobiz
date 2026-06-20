/** @type {import('next').NextConfig} */

// NEXT_PUBLIC_BACKEND_URL — baked into the JS bundle at build time; used directly by the browser.
// BACKEND_URL            — server-side only; sets the /backend rewrite proxy target at build time.
// For local Docker:  pass BACKEND_URL=http://backend:8000 as a build arg (proxy approach).
// For production:    pass NEXT_PUBLIC_BACKEND_URL=https://your-backend.com as a build arg.
const backendTarget = (
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  process.env.BACKEND_URL ||
  ""
).replace(/\/$/, "")

if (!backendTarget) {
  console.error(
    "ERROR: Neither NEXT_PUBLIC_BACKEND_URL nor BACKEND_URL is set. " +
    "The /backend rewrite proxy will be inactive. " +
    "Set one of these environment variables before building."
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
