# apps/web — sivra product app

Next.js 14 (App Router) + TypeScript + Tailwind + Prisma + Auth.js v5
(passwordless magic-link via Brevo). This is the hub described in the root
`ARCHITECTURE.md`: it owns Postgres and is the only writer of the product DB.

## Structure

```
apps/web/
├─ prisma/schema.prisma         # AUTHORITATIVE data model (do not edit here without coordination)
├─ src/
│  ├─ lib/
│  │  ├─ db.ts                  # Prisma singleton — import { prisma }
│  │  ├─ auth.ts                # Auth.js v5: PrismaAdapter + Email/magic-link (Brevo), DB sessions
│  │  ├─ brevo.ts               # sendEmail({to,subject,html}) via Brevo API
│  │  ├─ internal.ts            # assertInternal(req) — x-internal-token guard for Python services
│  │  └─ org.ts                 # requireSession / activeMembership / assertOrgAccess — ORG SCOPING
│  ├─ types/next-auth.d.ts      # adds user.id to the Session type
│  ├─ middleware.ts             # protects /app/* (session-cookie check)
│  └─ app/
│     ├─ layout.tsx             # Fraunces + Inter via next/font, design tokens
│     ├─ globals.css            # tokens (paper/ink/accent) + shared primitives
│     ├─ page.tsx               # landing
│     ├─ signin/page.tsx        # email → magic-link form (server action → signIn)
│     ├─ app/page.tsx           # protected dashboard: lists orgs / create-org form
│     └─ api/
│        ├─ auth/[...nextauth]/route.ts   # Auth.js handlers
│        └─ internal/ping/route.ts        # example internal route (assertInternal)
├─ scripts/roundtrip.ts         # DB round-trip smoke test
├─ Dockerfile                   # Next standalone, runs on $PORT
└─ railway.json                 # Dockerfile builder
```

## Run locally

```bash
cd apps/web
npm install              # also runs `prisma generate` (postinstall)
npm run db:push          # push schema.prisma to DATABASE_URL (Railway public proxy)
npx tsx scripts/roundtrip.ts   # optional: verify a create/read/delete round-trip
npm run dev              # http://localhost:3000
```

Sign-in sends a real magic-link email through Brevo, so `BREVO_API_KEY` and a
verified `BREVO_SENDER_EMAIL` must be set for the flow to complete.

## Environment

`apps/web/.env` (gitignored) holds:

```
DATABASE_URL          # Railway Postgres public proxy (local Prisma)
AUTH_SECRET           # openssl rand -base64 32
AUTH_URL              # http://localhost:3000 (set to https://sivra.io in prod)
BREVO_API_KEY
BREVO_SENDER_EMAIL    # no-reply@sivra.io
INTERNAL_API_TOKEN    # shared secret for /api/internal/* and /api/voice/*
```

In production set `DATABASE_URL` to the Railway internal URL
(`${{Postgres.DATABASE_URL}}`) and `AUTH_URL` to the public origin.

## Deploy (Railway)

Builder is the Dockerfile (`output: 'standalone'`). The container runs
`node server.js` on `$PORT`. Set the env vars above as Railway service
variables. Do not commit `.env`.

## Conventions for feature agents

- Read the DB with `import { prisma } from "@/lib/db"`. Never instantiate a new client.
- Read the session with `import { auth } from "@/lib/auth"` (or `requireSession()` from `@/lib/org`).
- **Every product query is scoped by orgId.** Call `assertOrgAccess(orgId)` from
  `@/lib/org` before any read/write touching org data.
- Routes called by Python services (`/api/internal/*`, `/api/voice/*`) must
  `assertInternal(req)` first — see `src/app/api/internal/ping/route.ts`.
- Money is integer cents. IDs are `cuid()`. Times are UTC.
```
