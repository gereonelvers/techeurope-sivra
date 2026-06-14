"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { StatusBadge } from "./_components/StatusBadge";
import { LocalDateTime } from "./_components/LocalDateTime";

// Orders hub — the single operational view. Server-rendered order rows come in
// as a prop; this client wrapper polls /api/fleet (~2.5s) and surfaces LIVE
// buyer-agent activity inline:
//   • per-order strips for SEARCHING orders whose category/brand/title matches a
//     live agent's goal/category, and
//   • a general "Live fleet" section for live agents we can't tie to an order.
// Honesty rule: Mission Control falls back to a bundled recorded REPLAY when no
// fleet is genuinely live. We only render agent tiles when source === "live";
// any replay/recorded/unknown source renders an explicit idle state (with a
// clearly-labelled link to the recorded Mission Control showcase).

export interface HubOrder {
  id: string;
  title: string;
  category: string | null;
  brand: string | null;
  maxBudgetCents: number | null;
  currency: string;
  status: string;
  requester: string | null;
  resultTitle: string | null;
  resultPriceCents: number | null;
  createdAt: string;
}

interface FleetAgent {
  agent_id?: string;
  site?: string;
  screenshot_url?: string | null;
  // Live agents send `action` as a structured object; replay sends a string.
  // Normalize via actionText() — never render raw (objects crash React).
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
  tick?: number | null;
  missionControlUrl?: string;
  error?: string;
}

const POLL_MS = 2500;
const DEFAULT_MC_URL = "https://mission-control-production-332c.up.railway.app";

// The ONLY source value we treat as genuinely live. Anything else — "replay",
// "recorded", null/undefined (Mission Control's bundled showcase) — is NOT live
// and must never be rendered as live agent activity.
function isLiveSource(source: string | null | undefined): boolean {
  return (source ?? "").toLowerCase() === "live";
}

const euros = (cents: number | null | undefined, currency = "EUR") =>
  cents == null
    ? "—"
    : new Intl.NumberFormat("en-IE", { style: "currency", currency }).format(cents / 100);

// Agent status → calm, status-keyed palette (mirrors StatusBadge's feel).
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

// Coerce any feed value to a safe string — live agents are loosely typed and a
// non-string reaching a JSX child throws "Objects are not valid as a React
// child", which crashes the whole page.
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

// Live agents send `action` as a structured object ({action:"click",x,y});
// the replay feed sends it pre-formatted. Render either as a tidy label.
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

// ── Tying live agents to orders ───────────────────────────────────────────────
// The live feed carries no order/mission id, so we match heuristically: a live
// agent belongs to a SEARCHING order when the agent's goal/category mentions the
// order's brand or category (brand is the stronger signal). Each agent is
// claimed by at most one order; the rest fall to the general "Live fleet".

function norm(s: string | null | undefined): string {
  return (s ?? "").toLowerCase();
}

function agentMatchesOrder(agent: FleetAgent, order: HubOrder): boolean {
  const haystack = `${norm(agent.goal)} ${norm(agent.category)}`;
  const brand = norm(order.brand);
  const category = norm(order.category);
  // Brand is specific → strong match. Category alone is a softer match.
  if (brand && haystack.includes(brand)) return true;
  if (category && haystack.includes(category)) return true;
  return false;
}

export function OrdersHub({ orders }: { orders: HubOrder[] }) {
  const [payload, setPayload] = useState<FleetPayload | null>(null);
  const [loaded, setLoaded] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    async function tick() {
      try {
        const res = await fetch("/api/fleet", { cache: "no-store" });
        const data = (await res.json()) as FleetPayload;
        if (alive.current) setPayload(data);
      } catch {
        if (alive.current) setPayload({ ok: false, agents: [], source: null });
      } finally {
        if (alive.current) {
          setLoaded(true);
          timer.current = setTimeout(tick, POLL_MS);
        }
      }
    }
    tick();
    return () => {
      alive.current = false;
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  const mcUrl = payload?.missionControlUrl || DEFAULT_MC_URL;
  const live = isLiveSource(payload?.source);
  // ONLY trust agents when the source is genuinely live. Replay → empty.
  const liveAgents = live ? (payload?.agents ?? []) : [];

  const searchingOrders = orders.filter((o) => o.status === "SEARCHING");

  // Claim each live agent for the first matching SEARCHING order; remainder →
  // general live fleet. Single pass so no agent is double-counted.
  const byOrder = new Map<string, FleetAgent[]>();
  const claimed = new Set<FleetAgent>();
  for (const order of searchingOrders) {
    const matched = liveAgents.filter(
      (a) => !claimed.has(a) && agentMatchesOrder(a, order),
    );
    if (matched.length > 0) {
      matched.forEach((a) => claimed.add(a));
      byOrder.set(order.id, matched);
    }
  }
  const unmatched = liveAgents.filter((a) => !claimed.has(a));

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold">Orders</h1>
          <p className="mt-2 text-sm leading-relaxed text-ink/60">
            Everything you've asked sivra to buy — searches, sign-offs, receipts —
            with the buyer fleet's live activity inline.
          </p>
        </div>
        <Link href="/app/orders/new" className="btn-accent shrink-0">
          New order
        </Link>
      </div>

      {/* Fleet status line — honest about live vs the recorded showcase. */}
      <FleetStatusLine loaded={loaded} live={live} count={liveAgents.length} mcUrl={mcUrl} />

      {orders.length === 0 ? (
        <div className="mt-8 rounded-2xl border border-dashed border-ink/15 bg-white/40 p-10 text-center">
          <p className="font-display text-lg font-semibold">No orders yet</p>
          <p className="mx-auto mt-2 max-w-sm text-sm text-ink/60">
            Describe what you need and a fleet of agents will go shopping. They'll
            escalate to the right person whenever a purchase needs sign-off.
          </p>
          <Link href="/app/orders/new" className="btn-accent mt-6">
            Start an order
          </Link>
        </div>
      ) : (
        <ul className="mt-6 space-y-2">
          {orders.map((o) => (
            <li key={o.id}>
              <Link
                href={`/app/orders/${o.id}`}
                className="flex items-center gap-4 rounded-xl border border-ink/10 bg-white/50 px-5 py-4 transition hover:border-ink/20 hover:bg-white/70"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">{o.title}</p>
                  <p className="mt-0.5 truncate text-xs text-ink/50">
                    {[o.brand, o.category, o.requester ? `· ${o.requester}` : null]
                      .filter(Boolean)
                      .join(" · ") || "—"}
                  </p>
                </div>
                <div className="hidden text-right sm:block">
                  <p className="text-sm font-medium">
                    {o.status === "COMPLETED" && o.resultPriceCents != null
                      ? euros(o.resultPriceCents, o.currency)
                      : o.maxBudgetCents != null
                        ? `≤ ${euros(o.maxBudgetCents, o.currency)}`
                        : "—"}
                  </p>
                  <p className="mt-0.5 text-xs text-ink/45">
                    <LocalDateTime iso={o.createdAt} dateOnly />
                  </p>
                </div>
                <StatusBadge status={o.status} />
              </Link>

              {/* Live agent strip — only for SEARCHING orders with live matches. */}
              {byOrder.has(o.id) ? (
                <OrderAgentStrip agents={byOrder.get(o.id)!} />
              ) : null}
            </li>
          ))}
        </ul>
      )}

      {/* Live agents we couldn't tie to a specific order. Live-only by design. */}
      {unmatched.length > 0 ? (
        <section className="mt-10">
          <div className="flex items-center gap-2">
            <span className="size-2 animate-pulse rounded-full bg-emerald-500" />
            <h2 className="text-lg font-semibold">Live fleet</h2>
            <span className="text-xs text-ink/45">
              {unmatched.length} agent{unmatched.length === 1 ? "" : "s"} not tied to an order
            </span>
          </div>
          <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {unmatched.map((a, i) => (
              <AgentTile key={a.agent_id ?? `u-${i}`} agent={a} />
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

// ── Fleet status line ─────────────────────────────────────────────────────────
function FleetStatusLine({
  loaded,
  live,
  count,
  mcUrl,
}: {
  loaded: boolean;
  live: boolean;
  count: number;
  mcUrl: string;
}) {
  if (!loaded) {
    return (
      <p className="mt-5 text-xs text-ink/45">Connecting to the fleet…</p>
    );
  }

  if (live && count > 0) {
    return (
      <div className="mt-5 flex flex-wrap items-center gap-2 text-xs text-ink/55">
        <span className="inline-flex items-center gap-1.5">
          <span className="size-2 animate-pulse rounded-full bg-emerald-500" />
          live fleet
        </span>
        <span className="text-ink/30">·</span>
        <span>
          {count} agent{count === 1 ? "" : "s"} working
        </span>
      </div>
    );
  }

  // Honest idle state — NOT showing the recorded replay as if it were live.
  return (
    <div className="mt-5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink/50">
      <span className="inline-flex items-center gap-1.5">
        <span className="size-2 rounded-full bg-ink/25" />
        No active searches — fleet idle
      </span>
      <span className="text-ink/30">·</span>
      <a
        href={mcUrl}
        target="_blank"
        rel="noreferrer"
        className="font-medium text-accent hover:opacity-80"
      >
        Watch the recorded demo in Mission Control →
      </a>
    </div>
  );
}

// ── Per-order live agent strip (compact) ──────────────────────────────────────
function OrderAgentStrip({ agents }: { agents: FleetAgent[] }) {
  return (
    <div className="ml-3 mt-1.5 grid grid-cols-1 gap-2 border-l-2 border-accent/20 pl-4 sm:grid-cols-2 lg:grid-cols-3">
      {agents.map((a, i) => (
        <AgentTile key={a.agent_id ?? `s-${i}`} agent={a} compact />
      ))}
    </div>
  );
}

// ── A single live agent tile ──────────────────────────────────────────────────
function AgentTile({ agent, compact = false }: { agent: FleetAgent; compact?: boolean }) {
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
      {/* Screenshot thumbnail */}
      <div className={`relative w-full bg-ink/5 ${compact ? "aspect-[16/9]" : "aspect-[16/10]"}`}>
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
          className={`absolute right-2 top-2 inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-semibold capitalize ${agentStatusStyle(statusStr)}`}
        >
          {statusStr || "—"}
        </span>
      </div>

      {/* Body */}
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
