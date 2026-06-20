/**
 * Resolves the backend API root at runtime, in priority order:
 *
 * 1. process.env.NEXT_PUBLIC_BACKEND_URL — baked at build time via Docker build arg
 *    or present in .env for local `npm run dev`.
 * 2. "/backend" — same-origin Next.js rewrite proxy, target set by BACKEND_URL build arg
 *    in next.config.mjs. Works for local Docker (browser→frontend→backend:8000).
 */
function resolveApiBase(): string {
  const buildTime = process.env.NEXT_PUBLIC_BACKEND_URL?.trim()
  if (buildTime) return buildTime
  return "/backend"
}

export const API_BASE = resolveApiBase()
