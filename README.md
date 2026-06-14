# sivra

**Procurement automation for the long tail of spend.** An employee asks sivra to
buy something — by chat or by phone — and a fleet of small **buyer agents** shops
a set of marketplaces in parallel. A **supervisor** aggregates their findings,
auto-buys when it is safe to, and otherwise **escalates to the right human at the
right urgency** (email, SMS, or a phone call). Every order is fully auditable, and
the routing model **retrains from human feedback**.

It targets *tail spend* — the high-volume, low-individual-value buying that is too
small to warrant a procurement officer per request but too frequent to ignore.
sivra was built as a {Tech: Europe} hackathon project; the live app is
[sivra.io](https://sivra.io).

> **Honesty note.** This is a hackathon build. The product app, the delegation/
> escalation path, voice and SMS intake, phone↔account linking, and the
> supervisor-orchestrated cloud fleet are all real and deployed. The buyer-agent
> **vision policy is the intentionally-incomplete part**: a small Gemma-family
> model was wired end-to-end on Modal but the overfit LoRA adapter has not been
> trained to accuracy, so the fleet's *navigation* is unreliable. To keep reports
> truthful the supervisor **grounds every candidate against real marketplace
> listings** and **cross-references the live web via Tavily** rather than trusting
> the agents' clicks. Places where something is a stub or demo lever are called out
> inline below.

---

## How it works

### The order lifecycle

```
intake (chat | voice | API)
   │
   ▼
Order(DRAFT) ──launch──▶ SEARCHING
   │                        │
   │            supervisor-orchestrated browsing fleet (Modal)
   │            • N buyer agents shop the marketplaces in parallel
   │            • Tavily searches the live web in parallel
   │            • supervisor narrates progress to the audit trail
   │            • candidates grounded against real listings
   │            • Gemini aggregates → ResearchReport (+ live-web results)
   │                        │
   │                        ▼
   │            app decides on the report:
   │            ┌───────────────────────────────┐
   │   inBudget │  AUTO-BUY  → PURCHASING        │ requester authorized
   │   & auth   │            → COMPLETED + receipt│ (approvalLimit ≥ price)
   │            └───────────────────────────────┘
   │            ┌───────────────────────────────┐
   │   else     │  ESCALATE → supervisor /route │
   │            │  → ONE Escalation + dispatch  │  (email / SMS / voice)
   │            │  → ESCALATED                  │
   │            └───────────────────────────────┘
   │                        │
   │            human answers on /d/<code> (or by voice)
   │            approve → COMPLETED · decline → CANCELLED
   │            counter/new context → RE-RESEARCH (round++, back to SEARCHING)
   ▼
every step writes an append-only OrderEvent (the audit backbone)
```

### The pieces

**1. The product app — `sivra.io` (`apps/web`).**
A Next.js 14 (App Router) application that is the hub and the **only writer of the
product database**. It owns auth, organizations/users, RBAC + per-org escalation
policies, the orders/fleet/escalations/settings UI, the audit timeline, and all
human-facing reply pages. The Python services are headless brains it calls over
HTTP; they never touch the DB directly. Chat intake is an OpenAI assistant
(`gpt-4o-mini` by default) that turns free text into a structured `Order`, with a
deterministic regex fallback so an order can always be created even with no API
key.

**2. The browsing fleet — Modal (`runtime/fleet_modal.py`).**
Launching an order POSTs `{orgId, orderId, goal, budgetCents, n, round}` to a
Modal web endpoint, which fire-and-forgets one container per order. Inside that
container a **supervisor agent (Gemini 3.1 Pro)** runs the whole mission:

- It spawns **N buyer agents** as concurrent asyncio tasks, each with its own
  Playwright `BrowserContext` in a single Chromium. N comes from the order's
  **fleet tier** — Small (3), Medium (12), or Deep (100) — set per-org and
  overridable per-order (`apps/web/src/lib/fleet-tiers.ts`). Deep runs are
  **concurrency-capped** (≈16 live contexts) and drain through a semaphore, so a
  100-agent search never opens 100 browsers at once.
- Each agent drives the marketplace through the **Modal vision endpoint**
  (`runtime/serve_modal.py`) in an observe→act→reward loop, and pushes a live
  screenshot tile (tagged with `orderId`) to the Mission Control dashboard ~once
  a second.
- The supervisor narrates the run into the order's audit trail as
  `supervisor_status` events ("Planning research…", "Dispatched N agents", "k/N
  done, cheapest so far €X"), **grounds the candidate list against the real
  cheapest matching listing per site** (via the marketplace's episode/reward
  oracle), and asks **Gemini** to aggregate everything into a `ResearchReport`
  (JSON: best candidate, alternatives, in/over budget, recommendation). A
  deterministic fallback report is always produced, so a missing Gemini key never
  blocks the mission.

- **A live-web search (Tavily) runs alongside the sandbox fleet.** The moment a
  search launches, the mission also fires a [Tavily](https://docs.tavily.com)
  query for the goal (visible in the audit trail: "Searching the live web
  (Tavily)…"). Its real-internet results — titles, source domains, links, and
  prices pulled from the snippets/answer by Gemini — fold into the same
  `ResearchReport` as a `webResults` array, with a guaranteed raw fallback if
  Gemini can't enrich them. These are a real-world cross-reference kept separate
  from the buyable marketplace inventory, so the report **always surfaces real
  options** even when the overfit agents come up thin; the order detail renders
  them under "From the live web".

  *Stub note:* because the vision LoRA is untrained, the truthful prices come from
  the grounding pass (and the Tavily cross-reference), not the agents' navigation.
  The agents are real and run; the report's numbers are deliberately not trusted to
  their clicks.

**3. The decision — back in the app (`/api/internal/orders/:id/research`).**
The fleet does **not** decide; it posts the report and the app reacts
(`apps/web/src/lib/research.ts` + the research route):

- **Auto-buy** when the report is in budget **and** the order's requester is
  authorized for the amount (their `Membership.approvalLimitCents` ≥ the best
  candidate's price). The order completes with a receipt — no human involved.
- **Escalate** otherwise (over budget, no match, or unauthorized requester): build
  a `DecisionRequest` from the report, call the supervisor's stateless `/route`
  with the org's policy, create **one** `Escalation` carrying the report, and
  dispatch a notification.

**4. The delegation supervisor — `supervisor/` (FastAPI, stateless).**
`POST /route` is a pure function over a guardrail + a router: given the
`DecisionRequest` and the org policy, it returns `{should_delegate,
target_purchasing_role, target_membership_id?, urgency_tier, suggested_message,
…}`. The router is the interesting part:

- A transparent **rules router** (`supervisor/router.py`) is the always-available
  baseline and the bootstrap labeler for the training set.
- A **Pioneer-fine-tuned router** (`pioneer/router_client.py`) plugs in behind the
  same signature when `PIONEER_ROUTER_MODEL` is set — a LoRA fine-tune of
  `Qwen/Qwen3-4B-Instruct-2507` served through the Pioneer (Fastino) API. It is
  **live in production** (see deployment notes). A GLiNER-style guardrail's
  `needs_signoff` always wins as a safety override.

**5. Dispatch — three delivery tiers (`apps/web/src/lib/dispatch.ts`).**
`notifyEscalation` always includes the unguessable `/d/<code>` reply link and
picks a channel by urgency:

| Urgency        | Channel                                   |
| -------------- | ----------------------------------------- |
| `ASYNC`        | **Email** (Brevo)                         |
| `URGENT_PUSH`  | **SMS** (Telnyx)                          |
| `VOICE`        | **Phone call** (ElevenLabs ConvAI) + SMS link as backup |

All side effects honor `DISPATCH_DRY_RUN` and never throw — the audit row is the
source of truth.

**6. Voice — inbound ordering + outbound escalation (`elevenlabs_voice/`).**
Two ElevenLabs Conversational AI agents share one phone number:

- **Inbound:** an employee *calls* and places an order by voice. The agent
  extracts title/budget/details and fires a `create_order` tool to
  `POST /api/voice/intake`.
- **Outbound:** for a `VOICE`-urgency escalation, the app calls the service, which
  places an ElevenLabs outbound call, explains the pending purchase, and posts the
  human's decision back via a `submit_decision` tool → `POST /api/voice/resolve`.

  *Tooling gotcha (real):* ElevenLabs webhook tools use a **static URL with all
  data in the body** (no path templating), so both tools target static app routes
  and carry their ids in the body.

**7. Phone ↔ account linking + call-in ordering (`apps/web/src/lib/phone-link.ts`).**
A verified `User.phone` (E.164) ties an inbound caller to an account and is where
escalations are sent. If an **unknown** number calls in, the app parks the order
in a **provisional account** and texts a CLAIM link; clicking it finishes sign-up
(email + workspace name) or merges the order into an existing account. A signed-in
user adding a phone gets a CONFIRM link instead. The SMS link *is* the proof of
phone ownership — only the holder receives it.

**8. Continual learning (`retrain_cron/` + `pioneer/`).**
Every resolved escalation stores a `rewardScalar` and an optional human
correction (`rating`, `correctedRole`, `correctedUrgency`). A daily Railway cron
service builds an SFT set from resolved escalations, fine-tunes a **challenger**
router on Pioneer, evaluates champion vs. challenger on a held-out set, and
**promotes by a DB write** (no redeploy) only if it doesn't regress. Online
corrections are also posted back to Pioneer adaptive inference. The promote/keep
history is surfaced in the admin page.

**9. Mission Control (`mission_control/`) + the marketplaces (`apps/marketplace/`).**
Mission Control is the live agent-grid dashboard — up to ~100 tiles, each a real
recorded (or live) computer-use trajectory. The app's `/api/fleet` proxies it and
only treats `source:"live"` as a live fleet, showing recorded replay honestly as
idle. `apps/marketplace/` is the shoppable target: three skinned marketplace
clones (`site-a/b/c`) backed by a seeded SQLite catalog, with a reward/episode
oracle the fleet uses both to shop and to ground candidate prices. It is the
**agent's target, not the product**.

---

## Tech stack

**Product app (`apps/web`)**
Next.js 14 (App Router) · React 18 · TypeScript · Tailwind · Prisma 5 →
PostgreSQL · Auth.js v5 (NextAuth beta) passwordless **magic-link** via Brevo ·
OpenAI (`gpt-4o-mini`) for chat intake. Money is integer cents; every product
query is org-scoped.

**Browsing fleet & vision**
Modal (GPU serving + the sandboxed browser fleet) · Playwright (Chromium) · a
fine-tuned **Gemma-family vision model** (`google/gemma-4-E2B-it` + LoRA, served
on an A100; trained with Unsloth `FastVisionModel` + TRL) · **Gemini 3.1 Pro**
supervisor for aggregation (falls back to `gemini-2.5-flash`) · **Tavily** for the
parallel live-web search that's folded into the research report.

**Delegation & comms**
FastAPI supervisor · **Pioneer (Fastino)** for the delegation router (a LoRA
fine-tune of `Qwen/Qwen3-4B-Instruct-2507`) · **ElevenLabs Conversational AI**
(inbound + outbound voice) · **Telnyx** (SMS + SIP telephony) · **Brevo**
(transactional email / magic links).

**Hosting**
**Railway** (the `web` app + Postgres + supervisor + voice + mission-control +
marketplace + the retrain cron) and **Modal** (vision serving + the browser
fleet), with **Cloudflare** in front of `sivra.io` (the apex is proxied because
Railway's per-domain cert issuance was rate-limited during the build).

---

## Repo layout

```
apps/
  web/               Next.js product app — sivra.io. Auth, orgs, orders, audit,
                     dispatch, all human UIs. OWNS Postgres (prisma/schema.prisma).
  marketplace/       The shoppable marketplace clones (site-a/b/c) + reward oracle.
                     The agents' target; seeded SQLite. NOT the product.

runtime/             The Modal browsing fleet:
  fleet_modal.py       supervisor-orchestrated mission (Gemini aggregation,
                       N-agent fleet, concurrency cap, fleet tiers).
  serve_modal.py       the Gemma-4 vision policy serving endpoint (LoRA-aware).
  agent_loop.py        one observe→act→reward episode.
  fleet.py             local N-agent runner that feeds Mission Control.

supervisor/          Stateless delegation brain — POST /route. Guardrail + rules
                     router + the Pioneer fine-tuned router.
pioneer/             Pioneer (Fastino) client, dataset/feedback builders, the
                     fine-tuned router, and the retrain driver.
retrain_cron/        Daily Railway cron: retrain → eval → promote the router.
vision_ft/           Gemma-4 vision LoRA fine-tune (Modal).
eval/                Pioneer-vs-frontier routing eval harness.

elevenlabs_voice/    Inbound order-taking + outbound escalation calls (ConvAI).
mission_control/     Live agent-grid dashboard (the demo hero visual).
orchestrator/        Local glue: free-text goal → live fleet → Mission Control.
                     (The deployed twin of this flow is runtime/fleet_modal.py.)
console/             Internal web console to exercise the SMS/voice tiers.

shared/contracts/    DecisionRequest / RoutingDecision / HumanResolution schema.
config/org.yaml      Person → contact → spend-authority routing table (legacy/local).
data/                Reward logs, datasets, eval sets (mostly gitignored).
demo/  scripts/      Offline checks + setup scripts.

ARCHITECTURE.md      The build's architecture contract (source of truth).
RESEARCH-FLOW.md     The research → decision (auto-buy vs escalate) flow.
```

> Some per-service READMEs predate the consolidation and describe pieces that have
> since been folded into `apps/web` (e.g. the legacy `supervisor/web.py` reply
> page, the standalone `orchestrator` UI, and the older `supervisor/escalate`
> fallback). The deployed flow is the one in `RESEARCH-FLOW.md` and
> `runtime/fleet_modal.py`.

---

## Running it

### Prerequisites

- **Node 18+** and **npm** (for `apps/web` and `apps/marketplace`).
- **PostgreSQL** for the app (a Railway Postgres URL, or local Postgres).
- **Python 3.11+** for the supervisor / fleet / pioneer services.
- **Modal** account (`MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET`) for vision serving
  and the fleet.
- API keys, by feature — each external service is isolated behind one client, so
  a missing key only disables that feature. See `.env.example` for the full list.

### Environment variables (by name — never commit values)

- **App:** `DATABASE_URL`, `AUTH_SECRET`, `AUTH_URL`, `INTERNAL_API_TOKEN`,
  `BREVO_API_KEY`, `BREVO_SENDER_EMAIL`, `OPENAI_API_KEY` (chat intake; optional).
- **Service URLs the app calls:** `ORCHESTRATOR_URL` (the Modal fleet endpoint —
  the **full** URL; the app POSTs to it directly), `SUPERVISOR_URL`,
  `ELEVENLABS_VOICE_URL`, `MISSION_CONTROL_URL`.
- **Dispatch:** `TELNYX_API_KEY`, `TELNYX_FROM`, `TELNYX_MESSAGING_PROFILE_ID`,
  `TELNYX_ALPHA_SENDER`; `DISPATCH_DRY_RUN` to log instead of send.
- **Router:** `PIONEER_API_KEY`, `PIONEER_ROUTER_MODEL`, `PIONEER_BASE_URL`.
- **Fleet (Modal secret `sivra-fleet`):** `INTERNAL_API_TOKEN`, `APP_INTERNAL_URL`,
  `MISSION_CONTROL_URL`, `MARKETPLACE_URL`, `VISION_ENDPOINT`, `GEMINI_API_KEY`;
  plus a separate Modal secret `tavily` → `TAVILY_API_KEY` (parallel live-web search).
- **Voice:** `ELEVEN_API_KEY`, `EL_AGENT_ID`, `EL_INBOUND_AGENT_ID`,
  `EL_PHONE_NUMBER_ID`.
- **Vision FT / Modal:** `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`,
  `HUGGINGFACE_API_KEY`.

### Run the app locally (`apps/web`)

```bash
cd apps/web
npm install            # runs `prisma generate` on postinstall
npm run db:push        # push prisma/schema.prisma to DATABASE_URL
npm run dev            # http://localhost:3000
```

Sign-in sends a real magic-link email through Brevo, so `BREVO_API_KEY` and a
verified `BREVO_SENDER_EMAIL` must be set for the login flow to complete.

### Run the marketplaces locally (`apps/marketplace`)

The buyer agents shop this. It ships a seeded SQLite DB; if it's missing,
`npm run db:push && npm run seed` rebuilds it.

```bash
cd apps/marketplace
npm install
npm run dev            # http://localhost:3000  (site-a / site-b / site-c)
```

### Deploy the Modal pieces

```bash
# vision policy serving endpoint (LoRA-aware; serves base until the adapter lands)
modal deploy runtime/serve_modal.py

# the supervisor-orchestrated browsing fleet (web endpoint = ORCHESTRATOR_URL)
modal deploy runtime/fleet_modal.py
```

The fleet reads its config from the Modal secret `sivra-fleet`. Trigger one
mission directly:

```bash
modal run runtime/fleet_modal.py --goal "cordless drill under 100 euros" --n 3
```

### Deploy the Railway services

Each service has its own Dockerfile + `railway.json`. With a project-scoped
`RAILWAY_TOKEN`:

```bash
railway up --service web              # the Next.js app → sivra.io
railway up --service supervisor       # the stateless routing brain
railway up --service elevenlabs-voice # inbound + outbound voice
railway up --service mission-control  # the agent-grid dashboard
railway up --service marketplace      # the shoppable clones
```

The router retrain runs as a Railway **cron** service (`retrain_cron/`,
schedule `0 3 * * *`) — see its README for the one-time setup.

### Quick checks (no external keys)

```bash
# offline routing + reward-loop check
python scripts/check_delegation.py

# prove the inbound/outbound voice agents WITHOUT placing a call
python elevenlabs_voice/simulate.py --resolution approve
python elevenlabs_voice/simulate_inbound.py
```

---

## Status, honestly

- **Live and deployed:** the `sivra.io` app, chat + voice intake, the
  supervisor-orchestrated cloud fleet, the auto-buy-vs-escalate decision, the
  three dispatch tiers, phone↔account linking with SMS sign-up, and the
  Pioneer-fine-tuned router (in production, with a cold-start caveat).
- **Real but with a known gap:** the buyer-agent **vision policy**. The Gemma-4
  serving + fine-tune plumbing is proven end-to-end on Modal, but the overfit LoRA
  hasn't been trained to accuracy, so agent navigation is unreliable. The
  supervisor compensates by grounding candidates against real listings; the report
  prices are truthful regardless.
- **Demo levers (off by default in the research flow):** the older
  `orchestrator/` path has a `FORCE_ESCALATE_STEP` lever to force an escalation for
  a demo when the untrained agents can't reach a real buy step. The current
  research flow does not force escalation — agents only research, and the app
  decides from the grounded report.
