// ResearchReport — the seam between the supervisor-orchestrated browsing fleet
// and the app's escalate-vs-auto-buy decision (see RESEARCH-FLOW.md). The
// supervisor (Gemini) aggregates each agent's best candidate into this exact
// shape and POSTs it to /api/internal/orders/:id/research. Money is integer
// cents; both sides use this shape verbatim.

export interface ResearchCandidate {
  title: string;
  priceCents: number;
  site?: string | null;
  url?: string | null;
  condition?: string | null;
}

export interface ResearchReport {
  /** Which research round produced this (0 = first pass; bumped on re-research). */
  round: number;
  /** Did the fleet find any matching candidate at all? */
  found: boolean;
  /** Human-readable one-liner the supervisor wrote (used as situation_text). */
  summary: string;
  /** The cheapest matching candidate (null when !found). */
  bestCandidate: ResearchCandidate | null;
  /** Runner-up options worth surfacing to the human. */
  alternatives?: ResearchCandidate[];
  /** bestCandidate.priceCents <= the order's budget cap. */
  inBudget: boolean;
  /** How far over budget the best candidate is, in cents (0 when in budget). */
  overBudgetByCents?: number | null;
  /** The supervisor's recommendation, e.g. "auto_buy" | "escalate_over_budget". */
  recommendation?: string | null;
  /** How many browsing agents ran for this round. */
  agentsRun?: number | null;
}

/** Coerce arbitrary JSON into a validated ResearchReport. Defensive — the
 * supervisor is trusted but field drift / partial reports shouldn't crash the
 * decision. Returns a normalized report with sane fallbacks. */
export function sanitizeReport(raw: unknown): ResearchReport {
  const r = (raw ?? {}) as Record<string, unknown>;

  const round = Number.isFinite(Number(r.round)) ? Math.max(0, Math.round(Number(r.round))) : 0;
  const found = Boolean(r.found);
  const summary = String(r.summary ?? "").trim();

  const bestCandidate = sanitizeCandidate(r.bestCandidate);
  const alternatives = Array.isArray(r.alternatives)
    ? r.alternatives.map(sanitizeCandidate).filter((c): c is ResearchCandidate => c != null)
    : [];

  const inBudget = Boolean(r.inBudget);
  const overBudgetByCents =
    r.overBudgetByCents == null
      ? null
      : Math.max(0, Math.round(Number(r.overBudgetByCents)));
  const recommendation = r.recommendation == null ? null : String(r.recommendation);
  const agentsRun =
    r.agentsRun == null ? null : Math.max(0, Math.round(Number(r.agentsRun)));

  return {
    round,
    found,
    summary,
    bestCandidate,
    alternatives,
    inBudget,
    overBudgetByCents,
    recommendation,
    agentsRun,
  };
}

function sanitizeCandidate(raw: unknown): ResearchCandidate | null {
  if (!raw || typeof raw !== "object") return null;
  const c = raw as Record<string, unknown>;
  const priceCents = Math.round(Number(c.priceCents));
  if (!Number.isFinite(priceCents)) return null;
  const title = String(c.title ?? "").trim();
  return {
    title: title || "Untitled item",
    priceCents: Math.max(0, priceCents),
    site: c.site == null ? null : String(c.site),
    url: c.url == null ? null : String(c.url),
    condition: c.condition == null ? null : String(c.condition),
  };
}
