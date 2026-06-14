# Research → Decision flow (supervisor-orchestrated fleet)

Replaces the old mid-search forced escalation. **Research (fleet) and the
escalation/decision are now SEPARATE stages**, with a `ResearchReport` as the seam.
A **supervisor agent (Gemini 3.1 Pro)** orchestrates the browsing fleet and aggregates.

## Flow
1. Order launched → app POSTs to `${ORCHESTRATOR_URL}` (Modal fleet root — note: POST to the
   root, NOT `/launch`) with `{orgId, orderId, goal, budgetCents, n, round}`.
2. **Supervisor mission (Modal, Gemini 3.1 Pro)** — `runtime/fleet_modal.py`:
   - Posts periodic STATUS updates to the audit trail:
     `POST {APP}/api/internal/orders/:id/event {type:"supervisor_status", actorType:"supervisor", message, data?}`
     (e.g. "Planning research…", "Dispatched 6 agents across 3 platforms", "3 candidates found, cheapest €X", "Best is €Y — €Z over budget").
   - Runs N browsing agents (the small overfit VLMs) shopping the marketplace; each pushes LIVE
     tiles to Mission Control **tagged with `orderId`** (existing). **Agents do NOT escalate** anymore.
   - Collects each agent's best candidate (title, priceCents, site, url, condition) — from the
     agent's episode result / the marketplace reward+events.
   - **Aggregates via Gemini** (GEMINI_API_KEY, model `gemini-3.1-pro`, fall back to `gemini-2.5-flash`)
     into a `ResearchReport`.
   - Posts it: `POST {APP}/api/internal/orders/:id/research {report}` (header `x-internal-token`).
3. **App decision** — `POST /api/internal/orders/:id/research` (assertInternal):
   - Store `report` on `Order.report`; append `OrderEvent("research_complete")`.
   - **AUTO-BUY** if `report.inBudget` AND the requester is authorized (the order's requester
     Membership `approvalLimitCents` >= `bestCandidate.priceCents`): complete the order
     (status COMPLETED, receipt from bestCandidate, events `purchased` + `completed`). **No human.**
   - **ELSE ESCALATE**: build a `DecisionRequest` from the report (`proposed_value`=bestCandidate
     price, `budget_cap`=order budget, `situation_text`=report.summary, `decision_type`) → call
     supervisor `${SUPERVISOR_URL}/route` with `buildPolicyPayload(orgId)` → create **ONE**
     `Escalation` carrying the report → dispatch (SMS/voice/email). Order → ESCALATED.
   - If `report.found` is false → escalate as "no match found — needs guidance".
4. **Resolution** (`resolve.ts`):
   - `approve` → complete with the report's bestCandidate (or the counter value).
   - `decline` → CANCELLED.
   - `counter` / notes with new context → **RE-RESEARCH**: re-launch the Modal fleet with a goal
     refined by the note (e.g. "iPhone 15 over budget → try iPhone 14"), `researchRound++`,
     status back to SEARCHING.

## ResearchReport (JSON — the seam; both sides use exactly this shape)
```json
{
  "round": 0,
  "found": true,
  "summary": "Cheapest matching cordless drill is a DeWalt at €92 on BidBay — €13 over the €79 cap.",
  "bestCandidate": { "title": "DeWalt DCD771", "priceCents": 9200, "site": "site-c", "url": "/site-c/item/238", "condition": "Good" },
  "alternatives": [ { "title": "Bosch GSR", "priceCents": 11000, "site": "site-a", "url": "/site-a/item/91" } ],
  "inBudget": false,
  "overBudgetByCents": 1300,
  "recommendation": "escalate_over_budget",
  "agentsRun": 6
}
```

## Visualization — order detail page `/app/orders/[id]`
- **Audit trail** (main): OrderEvents incl. the periodic `supervisor_status` updates, rendered in a
  distinct "supervisor" voice (vs user/agent/system).
- **Final report** (beside the audit, once `research_complete`): `Order.report` as a card — best
  option, price-vs-budget, alternatives, recommendation.
- **Browsing fleet** (below): live agent tiles for THIS order during research (Mission Control
  `source:live`, filtered by `orderId`); after the run ends, **clearly-marked "replay"**.
