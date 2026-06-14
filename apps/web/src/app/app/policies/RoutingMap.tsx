"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

// Live decision-routing map: how a purchase that needs sign-off is routed — by
// amount, to the right person, at the right urgency — with the org's recent
// escalations shown live underneath (and roles awaiting a decision pulsing).
// Polls /api/routing every few seconds.

interface Member {
  id: string;
  name: string;
  role: string | null; // purchasing role
  approvalLimitCents: number | null;
  phoneVerified: boolean;
}
interface Band {
  kind: "auto" | "human";
  lowerCents: number;
  maxCents: number | null;
  role: string | null;
  urgency: string | null;
}
interface Escalation {
  id: string;
  proposedValueCents: number | null;
  decisionType: string;
  targetRole: string | null;
  targetName: string | null;
  urgencyTier: string;
  status: string;
  resolution: string | null;
  resolvedByLabel: string | null;
  summary: string | null;
  orderTitle: string | null;
  orderId: string | null;
  currency: string;
  createdAt: string;
  resolvedAt: string | null;
}
interface RoutingData {
  members: Member[];
  bands: Band[];
  autoApproveMaxCents: number;
  escalations: Escalation[];
}

const euros = (cents: number | null | undefined, currency = "EUR") => {
  if (cents == null) return "—";
  try {
    return new Intl.NumberFormat("en-IE", {
      style: "currency",
      currency: currency || "EUR",
      maximumFractionDigits: 0,
    }).format(cents / 100);
  } catch {
    return `€${Math.round(cents / 100)}`;
  }
};

const ROLE_LABEL: Record<string, string> = {
  buyer: "Buyer",
  procurement_lead: "Procurement lead",
  manager: "Manager",
};
function roleLabel(role: string | null): string {
  return role ? ROLE_LABEL[role] ?? role : "—";
}

// urgency tier → human label + a little glyph. Handles both the policy's
// lowercase strings and the Escalation enum's UPPER_CASE.
function urgency(tier: string | null | undefined): { label: string; glyph: string } {
  const t = (tier ?? "").toLowerCase();
  if (t === "voice") return { label: "voice call", glyph: "📞" };
  if (t === "urgent_push" || t === "sms") return { label: "SMS", glyph: "✉️" };
  return { label: "in-app", glyph: "•" };
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "—";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function timeAgo(iso: string): string {
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function bandRange(b: Band, currency = "EUR"): string {
  if (b.kind === "auto") return `≤ ${euros(b.maxCents, currency)}`;
  if (b.maxCents == null) return `> ${euros(b.lowerCents, currency)}`;
  return `${euros(b.lowerCents, currency)}–${euros(b.maxCents, currency)}`;
}

const STATUS_STYLE: Record<string, { dot: string; text: string; label: string }> = {
  PENDING: { dot: "bg-amber-500", text: "text-amber-700", label: "awaiting" },
  RESOLVED: { dot: "bg-emerald-600", text: "text-emerald-700", label: "resolved" },
  EXPIRED: { dot: "bg-ink/40", text: "text-ink/50", label: "expired" },
};
function resolutionStyle(res: string | null): { glyph: string; text: string } {
  switch (res) {
    case "approve":
      return { glyph: "✓ approved", text: "text-emerald-700" };
    case "decline":
      return { glyph: "✕ declined", text: "text-red-700" };
    case "counter":
      return { glyph: "✎ countered", text: "text-accent" };
    default:
      return { glyph: "resolved", text: "text-ink/60" };
  }
}

export function RoutingMap() {
  const [data, setData] = useState<RoutingData | null>(null);
  const [, force] = useState(0); // re-render for "time ago"
  const stopped = useRef(false);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/routing", { cache: "no-store" });
      if (!res.ok) return;
      const d = (await res.json()) as RoutingData;
      if (!stopped.current) setData(d);
    } catch {
      /* keep last good */
    }
  }, []);

  useEffect(() => {
    stopped.current = false;
    load();
    const poll = setInterval(load, 4000);
    const tick = setInterval(() => force((n) => n + 1), 15000); // refresh timestamps
    return () => {
      stopped.current = true;
      clearInterval(poll);
      clearInterval(tick);
    };
  }, [load]);

  if (!data) {
    return (
      <div className="mt-6 h-56 animate-pulse rounded-2xl border border-ink/10 bg-white/40" />
    );
  }

  const memberFor = (role: string | null) =>
    role ? data.members.find((m) => m.role === role) ?? null : null;
  // Roles with a PENDING escalation right now → pulse their lane + person.
  const pendingByRole = new Set(
    data.escalations.filter((e) => e.status === "PENDING").map((e) => e.targetRole),
  );

  return (
    <section className="mt-7">
      {/* Local keyframes for the "flow" pulse along an active lane. */}
      <style>{`
        @keyframes sivra-flow { 0% { background-position: 0% 0 } 100% { background-position: -200% 0 } }
        @keyframes sivra-ping { 0% { transform: scale(1); opacity: .5 } 80%,100% { transform: scale(2.1); opacity: 0 } }
      `}</style>

      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Decision routing</h2>
          <p className="mt-0.5 max-w-prose text-sm text-ink/60">
            How sivra decides who signs off — and how loudly it pings them. Lanes
            awaiting a decision pulse live.
          </p>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-600/10 px-2.5 py-1 text-xs font-semibold text-emerald-800">
          <span className="size-2 animate-pulse rounded-full bg-emerald-500" /> live
        </span>
      </div>

      {/* The flow: incoming request → budget lanes → the people who sign off. */}
      <div className="mt-4 rounded-2xl border border-ink/10 bg-white/50 p-4 sm:p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-stretch">
          {/* Incoming request */}
          <div className="flex shrink-0 items-center lg:w-40">
            <div className="w-full rounded-xl border border-ink/15 bg-paper/60 p-3 text-center">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-ink/45">
                Incoming
              </p>
              <p className="mt-1 text-sm font-semibold leading-snug">
                Purchase needs sign-off
              </p>
              <p className="mt-1 text-xs text-ink/50">routed by amount →</p>
            </div>
          </div>

          {/* Lanes → people */}
          <div className="flex-1 space-y-2.5">
            {data.bands.map((b, i) => {
              const m = memberFor(b.role);
              const pending = b.role != null && pendingByRole.has(b.role);
              const u = urgency(b.urgency);
              return (
                <div key={i} className="flex items-center gap-2 sm:gap-3">
                  {/* band / amount + urgency */}
                  <div
                    className={`w-32 shrink-0 rounded-lg border px-2.5 py-2 sm:w-40 ${
                      b.kind === "auto"
                        ? "border-emerald-600/25 bg-emerald-50/50"
                        : pending
                          ? "border-accent/40 bg-accent/[0.05]"
                          : "border-ink/12 bg-white/70"
                    }`}
                  >
                    <p className="text-xs font-semibold tabular-nums">{bandRange(b)}</p>
                    <p className="mt-0.5 text-[11px] text-ink/55">
                      {b.kind === "auto" ? (
                        "auto-approved"
                      ) : (
                        <>
                          <span aria-hidden>{u.glyph}</span> {u.label}
                        </>
                      )}
                    </p>
                  </div>

                  {/* connector */}
                  <div className="relative h-6 flex-1">
                    <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-ink/15" />
                    <div
                      className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2"
                      style={{
                        backgroundImage:
                          "linear-gradient(90deg, transparent, transparent 40%, rgba(58,53,124,0.9) 50%, transparent 60%, transparent)",
                        backgroundSize: "200% 100%",
                        animation: `sivra-flow ${pending ? "1.1s" : "3.5s"} linear infinite`,
                        opacity: pending ? 1 : 0.4,
                      }}
                    />
                  </div>

                  {/* destination: a person, or "no human" for the auto band */}
                  {b.kind === "auto" ? (
                    <div className="flex w-32 shrink-0 items-center gap-2 rounded-xl border border-emerald-600/20 bg-emerald-50/40 px-2.5 py-2 sm:w-48">
                      <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-emerald-600/15 text-sm text-emerald-700">
                        ⚡
                      </span>
                      <div className="min-w-0">
                        <p className="truncate text-xs font-semibold text-emerald-800">
                          No human needed
                        </p>
                        <p className="text-[11px] text-emerald-700/70">bought instantly</p>
                      </div>
                    </div>
                  ) : (
                    <PersonNode role={b.role} member={m} pending={pending} />
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Live decisions feed */}
      <div className="mt-5">
        <div className="flex items-baseline justify-between">
          <h3 className="text-sm font-semibold">Live decisions</h3>
          <span className="text-xs text-ink/45">{data.escalations.length} recent</span>
        </div>
        {data.escalations.length === 0 ? (
          <p className="mt-2 rounded-xl border border-ink/10 bg-white/40 px-4 py-6 text-center text-sm text-ink/50">
            No sign-off requests yet — they'll stream in here as orders need approval.
          </p>
        ) : (
          <ul className="mt-2 space-y-1.5">
            {data.escalations.map((e) => {
              const st = STATUS_STYLE[e.status] ?? STATUS_STYLE.PENDING;
              const u = urgency(e.urgencyTier);
              const res = e.status === "RESOLVED" ? resolutionStyle(e.resolution) : null;
              const Row = (
                <div
                  className={`flex items-center gap-3 rounded-lg border px-3 py-2 text-sm ${
                    e.status === "PENDING"
                      ? "border-accent/25 bg-accent/[0.04]"
                      : "border-ink/10 bg-white/55"
                  }`}
                >
                  <span className="relative flex size-2.5 shrink-0">
                    {e.status === "PENDING" ? (
                      <span
                        className="absolute inset-0 rounded-full bg-amber-500"
                        style={{ animation: "sivra-ping 1.4s cubic-bezier(0,0,.2,1) infinite" }}
                      />
                    ) : null}
                    <span className={`relative size-2.5 rounded-full ${st.dot}`} />
                  </span>
                  <span className="shrink-0 font-semibold tabular-nums">
                    {euros(e.proposedValueCents, e.currency)}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-ink/75">
                    {e.orderTitle ?? e.summary ?? e.decisionType}
                    <span className="text-ink/40">
                      {" → "}
                      {e.targetName ?? roleLabel(e.targetRole)} · {u.glyph} {u.label}
                    </span>
                  </span>
                  {res ? (
                    <span className={`shrink-0 text-xs font-semibold ${res.text}`}>
                      {res.glyph}
                    </span>
                  ) : (
                    <span className="shrink-0 text-xs font-semibold text-amber-700">
                      awaiting
                    </span>
                  )}
                  <span className="shrink-0 text-xs tabular-nums text-ink/40">
                    {timeAgo(e.resolvedAt ?? e.createdAt)}
                  </span>
                </div>
              );
              return (
                <li key={e.id}>
                  {e.orderId ? (
                    <Link href={`/app/orders/${e.orderId}`} className="block transition hover:opacity-90">
                      {Row}
                    </Link>
                  ) : (
                    Row
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}

function PersonNode({
  role,
  member,
  pending,
}: {
  role: string | null;
  member: Member | null;
  pending: boolean;
}) {
  if (!member) {
    return (
      <div className="flex w-32 shrink-0 items-center gap-2 rounded-xl border border-dashed border-ink/20 bg-white/40 px-2.5 py-2 sm:w-48">
        <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-ink/8 text-xs text-ink/40">
          ?
        </span>
        <div className="min-w-0">
          <p className="truncate text-xs font-medium text-ink/55">{roleLabel(role)}</p>
          <p className="text-[11px] text-ink/40">unassigned</p>
        </div>
      </div>
    );
  }
  return (
    <div
      className={`flex w-32 shrink-0 items-center gap-2 rounded-xl border px-2.5 py-2 transition sm:w-48 ${
        pending
          ? "border-accent/50 bg-accent/[0.06] ring-2 ring-accent/20"
          : "border-ink/12 bg-white/70"
      }`}
    >
      <span className="relative flex size-7 shrink-0 items-center justify-center rounded-full bg-accent/15 text-[11px] font-bold text-accent">
        {initials(member.name)}
        {pending ? (
          <span
            className="absolute inset-0 rounded-full ring-2 ring-accent/50"
            style={{ animation: "sivra-ping 1.5s cubic-bezier(0,0,.2,1) infinite" }}
          />
        ) : null}
      </span>
      <div className="min-w-0">
        <p className="flex items-center gap-1 truncate text-xs font-semibold">
          {member.name}
          {member.phoneVerified ? (
            <span title="phone verified" className="size-1.5 rounded-full bg-emerald-500" />
          ) : null}
        </p>
        <p className="truncate text-[11px] text-ink/50">
          {roleLabel(member.role)}
          {member.approvalLimitCents != null
            ? ` · ${euros(member.approvalLimitCents)}`
            : ""}
        </p>
      </div>
    </div>
  );
}
