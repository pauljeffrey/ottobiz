# ── Stage 1: deps ─────────────────────────────────────────────────────────────
FROM node:20-alpine AS deps
WORKDIR /app

COPY package.json package-lock.json* ./
# Install ALL deps (including devDeps) — next build needs typescript, @types/*, etc.
RUN npm ci --legacy-peer-deps

# ── Stage 2: build ────────────────────────────────────────────────────────────
FROM node:20-alpine AS builder
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Both vars MUST be passed as Build Arguments in Dokploy.
# No localhost fallbacks — if missing, next.config.mjs will warn and skip the rewrite.
ARG BACKEND_URL=
ENV BACKEND_URL=$BACKEND_URL

ARG NEXT_PUBLIC_BACKEND_URL=
ENV NEXT_PUBLIC_BACKEND_URL=$NEXT_PUBLIC_BACKEND_URL

ARG FRAME_ANCESTORS=
ENV FRAME_ANCESTORS=$FRAME_ANCESTORS

RUN npm run build

# ── Stage 3: runner ───────────────────────────────────────────────────────────
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
# next start respects PORT; default 3000
ENV PORT=3000

RUN addgroup --system --gid 1001 nodejs \
 && adduser  --system --uid 1001 nextjs

# Copy build output and only production deps
COPY --from=builder /app/public        ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next ./.next
COPY --from=builder /app/package.json  ./package.json
COPY --from=builder /app/package-lock.json* ./
# Re-install prod-only deps for the lean final image
RUN npm ci --omit=dev --legacy-peer-deps && npm cache clean --force

USER nextjs

EXPOSE 3000

CMD ["npm", "run", "start"]
