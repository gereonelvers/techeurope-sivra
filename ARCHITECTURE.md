# sivra — architecture contract

Single source of truth for the consolidation build. Every subagent reads this first.
If something here conflicts with older per-service READMEs, **this wins**.

## Product
An employee asks sivra to buy something (by **phone call** to the ElevenLabs agent, or via a
**chat UI**). An orchestrator spawns a fleet of small vision agents that shop our marketplace
platforms. When a purchase needs sign-off it **escalates to the right person at the right urgency**
(SMS / push / voice). Every purchase is **fully auditable** by anyone involved. Multi-org, multi-user,
authenticated. Per-org **customizable escalation rules**. Models **retrain from feedback**.

## Flow
`intake (voice|chat) → Order(DRAFT) → launch → fleet searches platforms (SEARCHING) → candidate →
escalate to approver (ESCALATED) → approve/counter/decline → purchase (PURCHASING) → COMPLETED + receipt`,
with an append-only **OrderEvent** audit row at every step.

## Target topology
`sivra.io` = the **Next.js app** (`apps/web`). It is the hub + the only writer of the product DB.
Python services are headless brains it calls. Backend APIs at `api.sivra.io` (or their Railway URLs).

| Component | Tech | Responsibility | Deploy |
|---|---|---|---|
| **apps/web** | Next.js 14 (App Router) + TS + Tailwind + Prisma + Auth.js v5 | Auth, orgs/users, orders, **audit trail**, permission policies, chat intake UI, dashboards, human reply page, **dispatch** (SMS/voice/email), owns Postgres | Railway `web` → **sivra.io** |
| **Postgres** | Railway Postgres | product DB (schema in `apps/web/prisma/schema.prisma`) | Railway `Postgres` |
| **supervisor** | FastAPI (Python) | **stateless** routing brain: `POST /route` (DecisionRequest + policy → RoutingDecision). No storage. Keeps guardrail + Pioneer router. | Railway `supervisor` → api.sivra.io |
| **orchestrator+runtime** | FastAPI + Playwright | spawns the vision fleet for an order; pushes fleet state; emits escalations to the app; reports receipts | Railway `orchestrator` (new) / local |
| **elevenlabs-voice** | FastAPI | **outbound** escalation calls + **inbound** order-taking calls (ElevenLabs ConvAI) | Railway `elevenlabs-voice` |
| **Modal: buyer-vision-serve** | Modal | vision policy inference endpoint (LoRA adapter) | Modal |
| **Modal: buyer-vision-ft** | Modal | vision fine-tune / expert-iteration | Modal |
| **apps/marketplace** | Next.js + Prisma/SQLite | the shoppable "platforms" the fleet searches (site-a/b/c). Agent target, not the product. | local / Railway `marketplace` (new, optional) |

Services being **folded into apps/web** (their UIs replaced): `mission_control`, `console`,
`orchestrator/ui.py`, `supervisor/web.py` reply pages. Keep them running until the app replaces each.

## Data model
`apps/web/prisma/schema.prisma` is authoritative. Key entities: `Organization, User, Membership
(role + purchasingRole + approvalLimit), Invite, PermissionPolicy, Order, OrderEvent (audit),
ChatMessage, Escalation`. **Money is integer cents. Every product query is scoped by `orgId` from the
session — no exceptions.** Auth.js models (`Account/Session/VerificationToken`) included.

## App API surface (the integration contract)
Public/authed (browser, session-cookie):
- `POST /api/orders` create; `GET /api/orders` list; `GET /api/orders/:id` detail (+events+escalations) — all org-scoped.
- `POST /api/orders/:id/launch` → app calls orchestrator with org/order binding; status→SEARCHING.
- `POST /api/intake` chat-assistant turn; creates/refines/launches an Order. `POST /api/orders/:id/messages`.
- `GET /d/:code` + `POST /d/:code` tokenized human reply page (capability `code`, not guessable).
- org/member/policy CRUD under `/api/orgs/*`, `/api/invites/*`, `/api/policies/*`.

Internal (called by Python services; auth via header `x-internal-token: $INTERNAL_API_TOKEN`):
- `POST /api/internal/escalations` `{requestId, orgId, orderId?, decisionType, situationText,
  proposedValueCents?, budgetCapCents?, agentConfidence?, item?}` → app persists Escalation, calls
  supervisor `POST /route` with the org policy, stores RoutingDecision, **dispatches** the notification
  (SMS/voice/email to the resolved target), returns the RoutingDecision. **The fleet calls THIS instead
  of supervisor `/escalate`.**
- `GET /api/internal/escalations/:requestId/resolution` → 200 HumanResolution once resolved, else 404. (fleet polls this)
- `POST /api/internal/orders/:id/event` `{type, actorType, message?, data?}` → append OrderEvent (audit/mission updates).
- `POST /api/internal/orders/:id/result` `{resultItemId, resultTitle, resultPriceCents, receipt}` → completion.
- `POST /api/voice/intake` `{callerPhone, title, description?, maxBudgetCents?}` → inbound voice creates an Order (caller→user/org by phone). `POST /api/voice/resolve` `{request_id, resolution, value?, notes?, rating?, correctedRole?, correctedUrgency?, resolvedByLabel?}` → resolves an escalation from the ConvAI tool (static URL, id in body — see voice-tier memory).

Resolution write path (used by `/d/:code`, voice tool, UI): look up Escalation by `code` or `requestId`,
write resolution + compute reward scalar, update Escalation+Order, append audit event, fire order-progress.

## Supervisor (stateless) contract
`POST /route` body `{request: DecisionRequest, policy: {rules, autoApproveMaxCents, voiceOverageRatio,
members:[{purchasingRole, approvalLimitCents, membershipId}]}}` → `RoutingDecision`
`{should_delegate, target_purchasing_role, target_membership_id?, urgency_tier, suggested_message,
rationale, model_version, guardrail}`. Pure function over guardrail + Pioneer/rules router. No DB.
Existing contracts live in `shared/contracts/schema.py` (DecisionRequest/RoutingDecision/HumanResolution)
— reuse; extend additively, never break field names other services read.

## Dispatch (from apps/web, TS)
- **SMS**: Telnyx REST (`TELNYX_API_KEY`, `TELNYX_FROM`, alpha sender for US→DE). Reply via `/d/:code` link.
- **Voice**: `POST {ELEVENLABS_VOICE_URL}/call {request_id, to, context, person}` (existing service).
- **Email**: Brevo transactional API (`BREVO_API_KEY`) — sign-in magic links, invites, escalation notices, completion.

## Conventions
- Next.js **App Router**, server components by default; Prisma client singleton in `src/lib/db.ts`.
- Auth.js v5 (`next-auth@5` beta) + `@auth/prisma-adapter`, **Email (magic-link)** provider whose
  `sendVerificationRequest` calls **Brevo**. Database sessions. Helper `auth()` for the session.
- **Org scoping is mandatory** on every product query: derive `orgId` from session/active membership.
- Money = integer **cents**. IDs = `cuid()`. Times = UTC. Enums per schema.
- Design tokens (match existing sivra look): paper `#F4F2EB`, ink `#211f1a`, accent `#3A357C`,
  fonts **Fraunces** (display) + **Inter** (body). Calm, editorial, warm.
- Secrets from env only; never commit. `.env` (gitignored) holds `DATABASE_URL` (public proxy, for local
  Prisma) + `DATABASE_URL_INTERNAL` (for the deployed app to use as `${{Postgres.DATABASE_URL}}`).

## Env (names)
`DATABASE_URL, DATABASE_URL_INTERNAL, AUTH_SECRET, BREVO_API_KEY, BREVO_SENDER_EMAIL, INTERNAL_API_TOKEN,
SUPERVISOR_URL(api.sivra.io), ORCHESTRATOR_URL, ELEVENLABS_VOICE_URL, MISSION_CONTROL_URL, TELNYX_API_KEY,
TELNYX_FROM, TELNYX_MESSAGING_PROFILE_ID, TELNYX_ALPHA_SENDER, ELEVEN_API_KEY, MODAL endpoint, OPENAI/GEMINI`.

## Domain plan
Try to automate (Railway custom domain via GraphQL `Project-Access-Token` + Cloudflare API): `sivra.io`→`web`,
`api.sivra.io`→`supervisor`. The ElevenLabs ConvAI resolve tool currently posts to `sivra.io/resolve`;
**repoint it to the app** before flipping the apex. If the apex move is fiddly, app→`sivra.io` is the must;
API can stay on its Railway URL.

## Workstream ownership (avoid collisions)
- **W-foundation** (done first): `apps/web` skeleton, `prisma/`, auth scaffold, `src/lib/{db,auth,brevo}.ts`, design system, deploy config.
- **W-auth**: `apps/web` auth + `/api/orgs|invites|policies`, RBAC, org switcher, Brevo emails.
- **W-orders**: `apps/web` `/api/orders|intake`, chat UI, order pages, order lifecycle.
- **W-orchestrator**: `orchestrator/`, `runtime/` — org/order binding, escalation client → app internal API, receipts; verify Modal adapter serving.
- **W-supervisor**: `supervisor/` → stateless `/route`; policy-driven routing; retire `store.py`/`web.py`.
- **W-voice**: `elevenlabs_voice/` inbound agent + app `/api/voice/*`; repoint resolve tool.
- **W-audit-ui**: `apps/web` audit timeline + dashboards + fleet grid (fold mission_control).
- **W-retrain**: `pioneer/`, `vision_ft/`, `eval/` — feedback→retrain loops, runnable.
- **W-deploy**: Railway services + domains + Cloudflare; integration tests.
