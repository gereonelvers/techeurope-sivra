"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { StatusBadge } from "../_components/StatusBadge";
import { LocalDateTime } from "../_components/LocalDateTime";
import { InlineApprover } from "./InlineApprover";
import {
  FLEET_TIERS,
  FLEET_TIER_ORDER,
  fleetTierLabel,
  type FleetTier,
} from "@/lib/fleet-tiers";

interface OrderEvent {
  id: string;
  type: string;
  actorType: string;
  message: string | null;
  data: unknown;
  createdAt: string;
}

interface Escalation {
  id: string;
  requestId: string;
  code: string;
  status: string;
  decisionType: string;
  situationText: string;
  suggestedMessage: string | null;
  proposedValueCents: number | null;
  budgetCapCents: number | null;
  urgencyTier: string;
  targetPurchasingRole: string | null;
  targetMembershipId: string | null;
  resolution: string | null;
  resolvedValueCents: number | null;
  rating: string | null;
  resolvedByLabel: string | null;
  createdAt: string;
  resolvedAt: string | null;
}

interface ChatMessage {
  id: string;
  role: string;
  content: string;
  createdAt: string;
}

interface ResearchCandidate {
  title: string;
  priceCents: number;
  site?: string | null;
  url?: string | null;
  condition?: string | null;
}

interface WebResult {
  title: string | null;
  url: string;
  source?: string | null;
  priceCents?: number | null;
  snippet?: string | null;
}

interface ResearchReport {
  round: number;
  found: boolean;
  summary: string;
  bestCandidate: ResearchCandidate | null;
  alternatives?: ResearchCandidate[];
  inBudget: boolean;
  overBudgetByCents?: number | null;
  recommendation?: string | null;
  agentsRun?: number | null;
  // Real-web results from the parallel Tavily search (cross-reference, not buyable
  // inventory). See runtime/fleet_modal.py _tavily_search.
  webResults?: WebResult[];
}

interface Order {
  id: string;
  title: string;
  description: string | null;
  category: string | null;
  brand: string | null;
  maxBudgetCents: number | null;
  currency: string;
  status: string;
  intakeChannel: string;
  resultTitle: string | null;
  resultPriceCents: number | null;
  resultItemId: number | null;
  receipt: unknown;
  report: ResearchReport | null;
  researchRound: number;
  fleetTier: string | null;
  nAgents: number | null;
  createdAt: string;
  completedAt: string | null;
  events: OrderEvent[];
  escalations: Escalation[];
  messages: ChatMessage[];
}

interface FleetAgent {
  agent_id?: string;
  orderId?: string | null;
  site?: string;
  screenshot_url?: string | null;
  // Loosely typed on purpose: live agents send `action` as a structured object
  // ({action,x,y}); the replay feed sends a pre-formatted string. actionText()
  // normalizes both — never render this raw (objects crash React).
  action?: unknown;
  goal?: string | null;
  category?: string | null;
  status?: string | null;
  step?: number | null;
  n_steps?: number | null;
  reward?: number | null;
  success?: boolean | null;
}

interface FleetPayload {
  ok?: boolean;
  agents?: FleetAgent[];
  source?: string | null;
  missionControlUrl?: string;
}

const DEFAULT_MC_URL = "https://mission-control-production-332c.up.railway.app";

function isLiveSource(source: string | null | undefined): boolean {
  return (source ?? "").toLowerCase() === "live";
}

const AGENT_STATUS_STYLES: Record<string, string> = {
  searching: "bg-amber-500/15 text-amber-800",
  filtering: "bg-amber-500/15 text-amber-800",
  viewing: "bg-accent/15 text-accent",
  cart: "bg-accent/15 text-accent",
  checkout: "bg-emerald-600/15 text-emerald-800",
  done: "bg-emerald-600/15 text-emerald-800",
  failed: "bg-red-600/15 text-red-800",
  error: "bg-red-600/15 text-red-800",
};

function agentStatusStyle(status: string | null | undefined): string {
  return AGENT_STATUS_STYLES[(status ?? "").toLowerCase()] ?? "bg-ink/8 text-ink/60";
}

// Coerce any feed value to a safe string for rendering. The fleet feed is
// loosely typed: live agents arrive straight from the runtime, replay agents
// are pre-formatted. Never let a non-string reach a JSX child (React throws
// "Objects are not valid as a React child" — which crashes the whole page).
function asText(v: unknown, fallback = ""): string {
  if (v == null) return fallback;
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try {
    return JSON.stringify(v);
  } catch {
    return fallback;
  }
}

// The runtime emits `action` as a structured object ({action:"click",x,y});
// the replay feed pre-formats it as a string. Render either as a tidy label.
function actionText(action: unknown): string | null {
  if (action == null) return null;
  if (typeof action === "string") return action || null;
  if (typeof action === "object") {
    const a = action as Record<string, unknown>;
    const kind = typeof a.action === "string" ? a.action : null;
    if (kind === "click" && a.x != null && a.y != null) return `click (${a.x}, ${a.y})`;
    if (kind === "type" && a.text != null) return `type "${asText(a.text).slice(0, 40)}"`;
    if (kind === "scroll" && a.dy != null) return `scroll ${a.dy}`;
    if (kind === "navigate_back" || kind === "back") return "back";
    if (kind === "done") return a.item_id != null ? `done #${asText(a.item_id)}` : "done ✓";
    if (kind) return kind;
    const s = asText(action);
    return s && s !== "{}" ? s : null;
  }
  return asText(action) || null;
}

const euros = (cents: number | null | undefined, currency = "EUR") => {
  if (cents == null) return "—";
  try {
    return new Intl.NumberFormat("en-IE", {
      style: "currency",
      currency: currency || "EUR",
    }).format(cents / 100);
  } catch {
    return `€${(cents / 100).toFixed(2)}`;
  }
};

// Live order detail. Polls /api/orders/:id every ~3s, merges the append-only
// OrderEvents with the Escalations into one chronological audit timeline, and
// surfaces an inline approver for any PENDING escalation the viewer may act on.
export function OrderDetail({
  orderId,
  viewerMembershipId,
  viewerCanManage,
  orgDefaultFleetTier,
}: {
  orderId: string;
  viewerMembershipId: string;
  viewerCanManage: boolean;
  orgDefaultFleetTier: FleetTier;
}) {
  const [order, setOrder] = useState<Order | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [launching, setLaunching] = useState(false);
  const [launchTier, setLaunchTier] = useState<FleetTier>(orgDefaultFleetTier);
  const stopped = useRef(false);

  // Stable fleet tiles for THIS order. Mission Control holds ONE global live
  // snapshot, and /api/fleet alternates between (a) this order's live agents and
  // (b) a recorded replay or ANOTHER order's live push. On a (b) poll none of the
  // agents carry our orderId, so a naive `agents.filter(orderId === ...)` would
  // empty out and the tiles would flicker out. Instead we REMEMBER each agent
  // we've seen for this order, keyed by agent_id, and only ever update/add — never
  // clear — so a tile, once shown, stays put and updates in place.
  const seenAgents = useRef<Map<string, FleetAgent>>(new Map());
  const seenOrder = useRef<string[]>([]); // stable first-seen ordering of agent_ids
  // Bumped on every poll that carries agents for THIS order, to re-render with the
  // freshly-merged tiles. Also carries the CURRENT poll's live-honesty signal.
  const [fleetView, setFleetView] = useState<{
    mcUrl: string;
    // True only when the CURRENT poll's source is live AND it actually carried
    // agents for THIS order — so the green "live" badge stays honest.
    liveNow: boolean;
    tick: number;
  }>({ mcUrl: DEFAULT_MC_URL, liveNow: false, tick: 0 });

  const load = useCallback(async () => {
    try {
      const res = await fetch(`/api/orders/${orderId}`, { cache: "no-store" });
      if (res.status === 404) {
        setError("Order not found.");
        stopped.current = true;
        return;
      }
      if (!res.ok) return;
      const data = await res.json();
      setOrder(data.order);
    } catch {
      /* transient — keep last good state, retry next tick */
    }
  }, [orderId]);

  const loadFleet = useCallback(async () => {
    try {
      const res = await fetch(`/api/fleet`, { cache: "no-store" });
      const data = (await res.json()) as FleetPayload;
      const mcUrl = data?.missionControlUrl || DEFAULT_MC_URL;

      // Agents the CURRENT poll carried for THIS order. A replay / other-order /
      // empty / ok:false payload yields an empty list here.
      const mine = (data?.agents ?? []).filter(
        (a) => a.orderId === orderId && typeof a.agent_id === "string" && a.agent_id,
      );

      if (mine.length > 0) {
        // Merge in place: update existing tiles by agent_id, append new ones in
        // first-seen order. We never drop a remembered agent here.
        for (const a of mine) {
          const id = a.agent_id as string;
          if (!seenAgents.current.has(id)) seenOrder.current.push(id);
          seenAgents.current.set(id, a);
        }
        // This poll is genuinely live for THIS order only when MC reports "live"
        // AND it carried our agents — keep the green badge honest.
        setFleetView((v) => ({
          mcUrl,
          liveNow: isLiveSource(data?.source),
          tick: v.tick + 1,
        }));
      } else {
        // Replay / other order / transient empty / error: keep the remembered
        // tiles rendered, but the current poll is NOT live for this order.
        setFleetView((v) =>
          v.liveNow || v.mcUrl !== mcUrl
            ? { ...v, mcUrl, liveNow: false }
            : v,
        );
      }
    } catch {
      // Fetch error: keep the last-known tiles; just drop the live badge.
      setFleetView((v) => (v.liveNow ? { ...v, liveNow: false } : v));
    }
  }, [orderId]);

  useEffect(() => {
    load();
    loadFleet();
    const t = setInterval(() => {
      if (!stopped.current) {
        load();
        loadFleet();
      }
    }, 3000);
    return () => clearInterval(t);
  }, [load, loadFleet]);

  async function act(path: string, setBusy: (b: boolean) => void) {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(path, { method: "POST" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.error ?? "Action failed.");
      }
      await load();
    } catch {
      setError("Network error.");
    } finally {
      setBusy(false);
    }
  }

  // Launch carries the chosen fleet-size tier for this search.
  async function launch() {
    setLaunching(true);
    setError(null);
    try {
      const res = await fetch(`/api/orders/${orderId}/launch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fleetTier: launchTier }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.error ?? "Could not launch the search.");
      }
      await load();
    } catch {
      setError("Network error.");
    } finally {
      setLaunching(false);
    }
  }

  if (error && !order) {
    return (
      <div>
        <Link href="/app/orders" className="text-sm text-accent hover:opacity-80">
          ← Orders
        </Link>
        <p className="mt-6 text-sm text-ink/60">{error}</p>
      </div>
    );
  }

  if (!order) {
    return <p className="text-sm text-ink/50">Loading…</p>;
  }

  const timeline = buildTimeline(order);
  const actionablePending = order.escalations.filter(
    (e) =>
      e.status === "PENDING" &&
      (viewerCanManage || e.targetMembershipId === viewerMembershipId),
  );
  const canLaunch = order.status === "DRAFT";
  const canCancel = !["COMPLETED", "CANCELLED", "DECLINED"].includes(order.status);

  // Browsing fleet for THIS order: the REMEMBERED tiles (never cleared once
  // seen), in stable first-seen order. `liveNow` reflects the CURRENT poll — the
  // green "live" badge only shows when this poll was genuinely live AND carried
  // our agents; otherwise the tiles stay visible under the muted "last run"
  // treatment. (`fleetView.tick` is read so this recomputes after each merge.)
  void fleetView.tick;
  const mcUrl = fleetView.mcUrl;
  const myAgents = seenOrder.current
    .map((id) => seenAgents.current.get(id))
    .filter((a): a is FleetAgent => a != null);
  const live = fleetView.liveNow && myAgents.length > 0;
  // Show the fleet section while researching, or whenever we have tiles for it.
  const showFleet =
    order.status === "SEARCHING" || myAgents.length > 0;

  return (
    <div>
      <Link href="/app/orders" className="text-sm text-accent hover:opacity-80">
        ← Orders
      </Link>

      <div className="mt-4 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold leading-tight">{order.title}</h1>
          {order.description ? (
            <p className="mt-1.5 max-w-prose text-sm text-ink/60">{order.description}</p>
          ) : null}
        </div>
        <StatusBadge status={order.status} />
      </div>

      {error ? <p className="mt-3 text-sm text-red-700">{error}</p> : null}

      {/* Fields */}
      <dl className="mt-6 grid grid-cols-2 gap-x-6 gap-y-3 rounded-xl border border-ink/10 bg-white/50 p-5 text-sm sm:grid-cols-4">
        <Field label="Brand" value={order.brand ?? "—"} />
        <Field label="Category" value={order.category ?? "—"} />
        <Field label="Max budget" value={euros(order.maxBudgetCents, order.currency)} />
        <Field label="Intake" value={order.intakeChannel.toLowerCase()} />
        {order.status !== "DRAFT" ? (
          <Field label="Fleet" value={fleetTierLabel(order.fleetTier)} />
        ) : null}
      </dl>

      {/* Actions */}
      {(canLaunch || canCancel) && (
        <div className="mt-4 space-y-3">
          {/* Per-search fleet size (DRAFT only) */}
          {canLaunch ? (
            <div className="rounded-xl border border-ink/10 bg-white/50 p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-ink/45">
                Fleet size for this search
              </p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {FLEET_TIER_ORDER.map((t) => {
                  const meta = FLEET_TIERS[t];
                  const sel = launchTier === t;
                  return (
                    <button
                      key={t}
                      type="button"
                      onClick={() => setLaunchTier(t)}
                      aria-pressed={sel}
                      title={meta.blurb}
                      className={[
                        "rounded-lg border px-3 py-1.5 text-sm transition",
                        sel
                          ? "border-accent bg-accent/[0.08] font-semibold ring-1 ring-accent/40"
                          : "border-ink/10 bg-white/60 hover:border-ink/25",
                      ].join(" ")}
                    >
                      {meta.label}{" "}
                      <span className="text-xs tabular-nums text-ink/45">· {meta.n}</span>
                    </button>
                  );
                })}
              </div>
              <p className="mt-1.5 text-[11px] text-ink/45">{FLEET_TIERS[launchTier].blurb}</p>
            </div>
          ) : null}

          <div className="flex gap-2">
            {canLaunch ? (
              <button
                type="button"
                onClick={launch}
                disabled={launching}
                className="btn-accent"
              >
                {launching ? "Launching…" : "Launch search"}
              </button>
            ) : null}
            {canCancel ? (
              <button
                type="button"
                onClick={() => act(`/api/orders/${orderId}/cancel`, () => {})}
                className="rounded-lg border border-ink/15 bg-white/60 px-5 py-3 text-sm font-semibold text-ink/70 transition hover:border-ink/30"
              >
                Cancel order
              </button>
            ) : null}
          </div>
        </div>
      )}

      {/* Receipt */}
      {order.status === "COMPLETED" && order.resultTitle ? (
        <div className="mt-6 rounded-xl border border-emerald-600/20 bg-emerald-50/50 p-5">
          <p className="text-xs font-semibold uppercase tracking-wide text-emerald-800/70">
            Receipt
          </p>
          <p className="mt-1 font-display text-lg font-semibold">{order.resultTitle}</p>
          <p className="mt-0.5 text-sm text-ink/70">
            {euros(order.resultPriceCents, order.currency)}
            {order.resultItemId != null ? ` · item #${order.resultItemId}` : ""}
          </p>
          {order.receipt ? (
            <pre className="mt-3 max-h-48 overflow-auto rounded-lg bg-white/70 p-3 text-xs text-ink/70">
              {JSON.stringify(order.receipt, null, 2)}
            </pre>
          ) : null}
        </div>
      ) : null}

      {/* Final research report (once the supervisor has posted one) */}
      {order.report ? (
        <ReportCard
          report={order.report}
          budgetCents={order.maxBudgetCents}
          currency={order.currency}
        />
      ) : null}

      {/* Inline approver(s) */}
      {actionablePending.map((e) => (
        <InlineApprover
          key={e.id}
          escalation={e}
          currency={order.currency}
          onResolved={load}
        />
      ))}

      {/* Audit timeline */}
      <h2 className="mt-9 text-lg font-semibold">Audit trail</h2>
      <ol className="mt-4 space-y-0">
        {timeline.map((item, i) => {
          const isSupervisor = item.voice === "supervisor";
          return (
            <li key={item.key} className="relative flex gap-4 pb-5">
              {/* connector */}
              {i < timeline.length - 1 ? (
                <span className="absolute left-[7px] top-4 h-full w-px bg-ink/10" />
              ) : null}
              <span
                className={`relative mt-1 h-3.5 w-3.5 shrink-0 rounded-full border-2 border-paper ${item.dot}`}
              />
              <div className="min-w-0 flex-1">
                {isSupervisor ? (
                  // Distinct "supervisor" voice — the orchestrating brain speaks
                  // in its own indigo card, set apart from user/agent/system.
                  <div className="rounded-lg border border-accent/25 bg-accent/[0.05] px-3.5 py-2.5">
                    <div className="flex items-baseline justify-between gap-3">
                      <p className="flex items-center gap-1.5 text-sm font-semibold text-accent">
                        <span className="inline-flex items-center rounded-full bg-accent/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide">
                          Supervisor
                        </span>
                        {item.title}
                      </p>
                      <time className="shrink-0 text-xs text-ink/40">
                        <LocalDateTime iso={item.at} />
                      </time>
                    </div>
                    {item.detail ? (
                      <p className="mt-1 text-sm text-ink/75">{item.detail}</p>
                    ) : null}
                    {item.meta ? (
                      <p className="mt-0.5 text-xs text-accent/70">{item.meta}</p>
                    ) : null}
                  </div>
                ) : (
                  <>
                    <div className="flex items-baseline justify-between gap-3">
                      <p className="text-sm font-medium">{item.title}</p>
                      <time className="shrink-0 text-xs text-ink/40">
                        <LocalDateTime iso={item.at} />
                      </time>
                    </div>
                    {item.detail ? (
                      <p className="mt-0.5 text-sm text-ink/60">{item.detail}</p>
                    ) : null}
                    {item.meta ? (
                      <p className="mt-0.5 text-xs text-ink/45">{item.meta}</p>
                    ) : null}
                  </>
                )}
              </div>
            </li>
          );
        })}
      </ol>

      {/* Browsing fleet for THIS order */}
      {showFleet ? (
        <FleetSection
          agents={myAgents}
          live={live}
          searching={order.status === "SEARCHING"}
          mcUrl={mcUrl}
        />
      ) : null}
    </div>
  );
}

// ── Final research report card ─────────────────────────────────────────────────
function ReportCard({
  report,
  budgetCents,
  currency,
}: {
  report: ResearchReport;
  budgetCents: number | null;
  currency: string;
}) {
  const best = report.bestCandidate;
  const over = report.overBudgetByCents ?? null;
  return (
    <div className="mt-6 rounded-xl border border-accent/20 bg-accent/[0.04] p-5">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-accent">
          Research report
          {report.round > 0 ? ` · round ${report.round + 1}` : ""}
        </p>
        {report.agentsRun != null ? (
          <span className="text-xs text-ink/45">{report.agentsRun} agents ran</span>
        ) : null}
      </div>

      {report.summary ? (
        <p className="mt-2 text-sm text-ink/80">{report.summary}</p>
      ) : null}

      {best ? (
        <div className="mt-4 rounded-lg border border-ink/10 bg-white/70 p-4">
          <p className="text-xs uppercase tracking-wide text-ink/45">Best option</p>
          <div className="mt-1 flex items-baseline justify-between gap-3">
            <p className="font-display text-base font-semibold">{best.title}</p>
            <p className="shrink-0 text-base font-semibold tabular-nums">
              {euros(best.priceCents, currency)}
            </p>
          </div>
          <p className="mt-0.5 text-xs text-ink/50">
            {[best.site, best.condition].filter(Boolean).join(" · ") || "—"}
          </p>
          {/* price vs budget */}
          <p className="mt-2 text-sm font-medium">
            {report.inBudget ? (
              <span className="text-emerald-700">
                In budget
                {budgetCents != null
                  ? ` — €${((budgetCents - best.priceCents) / 100).toFixed(2)} under cap`
                  : ""}
              </span>
            ) : (
              <span className="text-red-700">
                Over budget
                {over != null ? ` by ${euros(over, currency)}` : ""}
              </span>
            )}
          </p>
        </div>
      ) : (
        <p className="mt-3 rounded-lg border border-amber-500/25 bg-amber-50/60 p-3 text-sm text-amber-900">
          No matching in-budget option was found — needs guidance.
        </p>
      )}

      {report.alternatives && report.alternatives.length > 0 ? (
        <div className="mt-4">
          <p className="text-xs uppercase tracking-wide text-ink/45">Alternatives</p>
          <ul className="mt-1.5 space-y-1.5">
            {report.alternatives.map((alt, i) => (
              <li
                key={`${alt.title}-${i}`}
                className="flex items-baseline justify-between gap-3 text-sm"
              >
                <span className="min-w-0 truncate text-ink/80">
                  {alt.title}
                  {alt.site ? <span className="text-ink/40"> · {alt.site}</span> : null}
                </span>
                <span className="shrink-0 tabular-nums text-ink/70">
                  {euros(alt.priceCents, currency)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {report.recommendation ? (
        <p className="mt-4 text-xs text-ink/55">
          <span className="font-semibold uppercase tracking-wide text-ink/45">
            Recommendation:{" "}
          </span>
          {report.recommendation.replace(/_/g, " ")}
        </p>
      ) : null}

      {/* Real-web cross-reference (Tavily), gathered alongside the fleet. */}
      {report.webResults && report.webResults.length > 0 ? (
        <div className="mt-5 border-t border-ink/10 pt-4">
          <p className="flex items-center gap-2 text-xs uppercase tracking-wide text-ink/45">
            From the live web
            <span className="rounded-full bg-ink/8 px-1.5 py-0.5 text-[9px] font-semibold normal-case tracking-normal text-ink/50">
              Tavily
            </span>
          </p>
          <ul className="mt-2 space-y-2">
            {report.webResults.slice(0, 5).map((w, i) => (
              <li key={`${w.url}-${i}`}>
                <a
                  href={w.url}
                  target="_blank"
                  rel="noreferrer"
                  className="group block rounded-lg border border-ink/10 bg-white/50 px-3 py-2 transition hover:border-accent/30"
                >
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="min-w-0 truncate text-sm font-medium text-ink/85 group-hover:text-accent">
                      {asText(w.title) || w.url}
                    </span>
                    {w.priceCents != null ? (
                      <span className="shrink-0 text-sm font-semibold tabular-nums">
                        {euros(w.priceCents, currency)}
                      </span>
                    ) : null}
                  </div>
                  {w.source || w.snippet ? (
                    <div className="mt-0.5 flex items-baseline gap-2 text-xs text-ink/45">
                      {w.source ? (
                        <span className="shrink-0 font-medium text-ink/55">
                          {asText(w.source)}
                        </span>
                      ) : null}
                      {w.snippet ? (
                        <span className="min-w-0 truncate">{asText(w.snippet)}</span>
                      ) : null}
                    </div>
                  ) : null}
                </a>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

// ── Browsing fleet (live tiles for this order, or last-run replay) ─────────────
function FleetSection({
  agents,
  live,
  searching,
  mcUrl,
}: {
  agents: FleetAgent[];
  live: boolean;
  searching: boolean;
  mcUrl: string;
}) {
  const isLive = live && agents.length > 0;
  return (
    <section className="mt-9">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-lg font-semibold">Browsing fleet</h2>
        {isLive ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-600/10 px-2.5 py-0.5 text-xs font-semibold text-emerald-800">
            <span className="size-2 animate-pulse rounded-full bg-emerald-500" />
            live
          </span>
        ) : agents.length > 0 ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-ink/8 px-2.5 py-0.5 text-xs font-semibold text-ink/55">
            <span className="size-2 rounded-full bg-ink/30" />
            replay / last run
          </span>
        ) : (
          <span className="text-xs text-ink/45">
            {searching ? "waiting for agents…" : "no agents tied to this order"}
          </span>
        )}
      </div>

      {agents.length > 0 ? (
        <>
          {!isLive ? (
            <p className="mt-2 text-xs text-ink/50">
              The fleet isn&apos;t live right now — these are the last frames from
              this order&apos;s most recent run.
            </p>
          ) : null}
          <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {agents.map((a, i) => (
              <AgentTile key={a.agent_id ?? `a-${i}`} agent={a} />
            ))}
          </div>
        </>
      ) : (
        <p className="mt-3 text-xs text-ink/50">
          No live tiles for this order yet.{" "}
          <a
            href={mcUrl}
            target="_blank"
            rel="noreferrer"
            className="font-medium text-accent hover:opacity-80"
          >
            Open Mission Control →
          </a>
        </p>
      )}
    </section>
  );
}

// ── A single agent tile (mirrors the hub's styling) ────────────────────────────
function AgentTile({ agent }: { agent: FleetAgent }) {
  const steps =
    agent.step != null && agent.n_steps != null
      ? `${agent.step}/${agent.n_steps}`
      : null;
  const pct =
    agent.step != null && agent.n_steps && agent.n_steps > 0
      ? Math.min(100, Math.round((agent.step / agent.n_steps) * 100))
      : null;
  const statusStr =
    typeof agent.status === "string" ? agent.status : asText(agent.status);
  const goalStr =
    asText(agent.goal) ||
    asText(agent.category) ||
    asText(agent.agent_id) ||
    "agent";
  const action = actionText(agent.action);

  return (
    <div className="overflow-hidden rounded-xl border border-ink/10 bg-white/60">
      <div className="relative aspect-[16/10] w-full bg-ink/5">
        {agent.screenshot_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={agent.screenshot_url}
            alt={goalStr}
            className="size-full object-cover"
            loading="lazy"
          />
        ) : (
          <div className="flex size-full items-center justify-center text-xs text-ink/35">
            no preview
          </div>
        )}
        <span
          className={`absolute right-2 top-2 inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-semibold capitalize ${agentStatusStyle(
            statusStr,
          )}`}
        >
          {statusStr || "—"}
        </span>
      </div>
      <div className="px-3.5 py-2.5">
        <div className="flex items-baseline justify-between gap-2">
          <p className="truncate text-sm font-medium">{goalStr}</p>
          {steps ? (
            <span className="shrink-0 text-[11px] tabular-nums text-ink/45">{steps}</span>
          ) : null}
        </div>
        <p className="mt-0.5 truncate text-xs text-ink/50">
          {[asText(agent.agent_id), asText(agent.site)].filter(Boolean).join(" · ") || "—"}
        </p>
        {action ? (
          <p className="mt-1 truncate font-mono text-[11px] text-ink/45">{action}</p>
        ) : null}
        {pct != null ? (
          <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-ink/10">
            <div
              className="h-full rounded-full bg-accent/70 transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-ink/45">{label}</dt>
      <dd className="mt-0.5 font-medium capitalize">{value}</dd>
    </div>
  );
}

// ── Timeline merge: OrderEvents + Escalations → one chronological list ──────────
interface TimelineItem {
  key: string;
  at: string;
  title: string;
  detail?: string;
  meta?: string;
  dot: string;
  /** Which "voice" speaks this entry — supervisor entries render distinctly. */
  voice?: "supervisor" | "default";
}

const EVENT_TITLES: Record<string, string> = {
  created: "Order created",
  search_started: "Search launched",
  agent_spawned: "Agent spawned",
  candidate_found: "Candidate found",
  supervisor_status: "Supervisor update",
  research_complete: "Research complete",
  re_research: "Re-researching",
  escalated: "Escalated for sign-off",
  notified: "Approver notified",
  approved: "Approved",
  countered: "Countered",
  declined: "Declined",
  purchased: "Purchased",
  completed: "Completed",
  failed: "Failed",
  note: "Note",
  message: "Chat message",
};

function dotFor(type: string): string {
  if (["approved", "completed", "purchased"].includes(type)) return "bg-emerald-600";
  if (["declined", "failed"].includes(type)) return "bg-red-600";
  if (["escalated", "notified", "supervisor_status", "research_complete", "re_research", "countered"].includes(type))
    return "bg-accent";
  if (["search_started", "candidate_found", "agent_spawned"].includes(type))
    return "bg-amber-500";
  return "bg-ink/40";
}

// Events spoken in the supervisor's voice (the orchestrating brain).
const SUPERVISOR_EVENTS = new Set([
  "supervisor_status",
  "research_complete",
  "re_research",
]);

// Per-agent events arrive one-per-agent and would flood the trail (12 "Agent
// spawned" rows on a Medium run). Collapse each such type into ONE summary row.
const COLLAPSIBLE_EVENTS = new Set([
  "agent_spawned",
  "agent_finished",
  "candidate_found",
]);

function collapsedTitle(type: string, count: number): string {
  if (count <= 1) return EVENT_TITLES[type] ?? type;
  switch (type) {
    case "agent_spawned":
      return `${count} agents spawned`;
    case "agent_finished":
      return `${count} agents finished`;
    case "candidate_found":
      return `${count} candidates found`;
    default:
      return `${EVENT_TITLES[type] ?? type} ×${count}`;
  }
}

function buildTimeline(order: Order): TimelineItem[] {
  const items: TimelineItem[] = [];
  // type → { count, earliest timestamp } for the collapsed per-agent rows.
  const grouped = new Map<string, { count: number; at: string }>();

  for (const e of order.events) {
    if (COLLAPSIBLE_EVENTS.has(e.type)) {
      const g = grouped.get(e.type);
      if (!g) {
        grouped.set(e.type, { count: 1, at: e.createdAt });
      } else {
        g.count += 1;
        if (new Date(e.createdAt).getTime() < new Date(g.at).getTime()) {
          g.at = e.createdAt;
        }
      }
      continue;
    }
    const isSupervisor =
      e.actorType === "supervisor" || SUPERVISOR_EVENTS.has(e.type);
    items.push({
      key: `ev-${e.id}`,
      at: e.createdAt,
      title: EVENT_TITLES[e.type] ?? e.type,
      detail: e.message ?? undefined,
      meta: actorLabel(e.actorType),
      dot: dotFor(e.type),
      voice: isSupervisor ? "supervisor" : "default",
    });
  }

  // One summary row per collapsed per-agent event type, at its earliest time.
  for (const [type, g] of grouped) {
    items.push({
      key: `grp-${type}`,
      at: g.at,
      title: collapsedTitle(type, g.count),
      meta: "by the buyer fleet",
      dot: dotFor(type),
      voice: "default",
    });
  }

  // Escalations add a "who-was-asked-what" node + (if resolved) a decision node.
  for (const esc of order.escalations) {
    const ask = esc.suggestedMessage || esc.situationText;
    items.push({
      key: `esc-${esc.id}`,
      at: esc.createdAt,
      title: `Asked ${esc.targetPurchasingRole ?? "an approver"} (${(esc.urgencyTier ?? "")
        .toLowerCase()
        .replace("_", " ")})`,
      detail: ask,
      meta: `${esc.decisionType}${
        esc.proposedValueCents != null
          ? ` · proposed ${euros(esc.proposedValueCents, order.currency)}`
          : ""
      }`,
      dot: "bg-accent",
    });
    if (esc.status === "RESOLVED" && esc.resolvedAt) {
      items.push({
        key: `esc-res-${esc.id}`,
        at: esc.resolvedAt,
        title: `${capitalize(esc.resolution ?? "resolved")} by ${
          esc.resolvedByLabel ?? "approver"
        }`,
        detail:
          esc.resolvedValueCents != null
            ? `at ${euros(esc.resolvedValueCents, order.currency)}`
            : undefined,
        meta: esc.rating ? `feedback: ${esc.rating}` : undefined,
        dot: esc.resolution === "decline" ? "bg-red-600" : "bg-emerald-600",
      });
    }
  }

  items.sort((a, b) => new Date(a.at).getTime() - new Date(b.at).getTime());
  return items;
}

function actorLabel(actorType: string): string {
  switch (actorType) {
    case "user":
      return "by the requester";
    case "agent":
      return "by a buyer agent";
    case "approver":
      return "by the approver";
    case "supervisor":
      return "by the supervisor";
    default:
      return "by sivra";
  }
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
