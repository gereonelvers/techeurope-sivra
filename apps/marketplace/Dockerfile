# ---------------------------------------------------------------------------
# Marketplace (Next.js 14 App Router + Prisma + SQLite) for Railway.
#
# Multi-stage build producing a small standalone runtime:
#   - deps    : install full deps (postinstall runs `prisma generate`)
#   - builder : prisma generate + DETERMINISTIC seed + next build
#   - runner  : node server.js on $PORT, with the SEEDED prisma/dev.db baked in
#
# SQLite handling: the seed (prisma/seed.ts, faker.seed(42)) is DETERMINISTIC, so
# the build re-creates the exact same ~750-listing catalog as the committed
# prisma/dev.db and bakes that db into the image. (We seed in-build rather than
# uploading the file because `railway up` honours .gitignore, which excludes
# *.db — so the committed db never reaches Railway's build context.) DATABASE_URL
# points at the baked db (file:/app/prisma/dev.db). Episode/Event writes during
# fleet runs land in this db inside the container's writable layer, so they are
# EPHEMERAL — they reset on every redeploy. The catalog (Listing rows the fleet
# shops) is immutable, deterministic seed data.
# ---------------------------------------------------------------------------

# ---- deps -----------------------------------------------------------------
FROM node:20-slim AS deps
# Prisma needs OpenSSL present to pick the right query-engine binary.
RUN apt-get update -y && apt-get install -y --no-install-recommends openssl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY package.json package-lock.json ./
COPY prisma ./prisma
# `npm ci` triggers the postinstall `prisma generate`, which needs the schema.
RUN npm ci

# ---- builder --------------------------------------------------------------
FROM node:20-slim AS builder
RUN apt-get update -y && apt-get install -y --no-install-recommends openssl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
# Build-time DB lives at a fixed absolute path; create + seed it here.
ENV DATABASE_URL="file:/app/prisma/dev.db"
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Create the SQLite schema then run the deterministic seed (faker.seed(42)) so
# the baked db matches the committed catalog exactly (~750 listings). This makes
# the image self-contained and independent of whether the committed dev.db file
# was carried in the upload context.
RUN npx prisma db push --skip-generate --accept-data-loss \
    && npm run seed
# `npm run build` == `prisma generate && next build` (standalone output).
RUN npm run build

# ---- runner ---------------------------------------------------------------
FROM node:20-slim AS runner
RUN apt-get update -y && apt-get install -y --no-install-recommends openssl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
# Absolute path: Prisma resolves a relative SQLite url against the *schema*
# directory (prisma/), not the process CWD, so an absolute file path is the
# unambiguous way to point at the baked db at /app/prisma/dev.db.
ENV DATABASE_URL="file:/app/prisma/dev.db"

# Next.js standalone server: server.js + minimal node_modules trace.
COPY --from=builder /app/.next/standalone ./
# Static assets (this app has no /public dir — images come from picsum.photos).
COPY --from=builder /app/.next/static ./.next/static

# Prisma needs: the generated client (in node_modules/.prisma & @prisma/client),
# the schema, and the engine. The standalone trace usually pulls the client +
# engine in, but copy the generated artifacts explicitly to be safe.
COPY --from=builder /app/node_modules/.prisma ./node_modules/.prisma
COPY --from=builder /app/node_modules/@prisma/client ./node_modules/@prisma/client
COPY --from=builder /app/prisma/schema.prisma ./prisma/schema.prisma

# The deterministically-seeded database, baked into the image.
COPY --from=builder /app/prisma/dev.db ./prisma/dev.db

# Railway injects $PORT; Next standalone reads PORT/HOSTNAME from env.
ENV HOSTNAME="0.0.0.0"
EXPOSE 3000
CMD ["node", "server.js"]
