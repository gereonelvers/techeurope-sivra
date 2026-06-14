import Link from "next/link";
import { requireSession, activeOrg, assertOrgAccess, canManageOrg } from "@/lib/org";
import { prisma } from "@/lib/db";
import { formatCents } from "@/lib/orders";
import { StatusBadge } from "./orders/_components/StatusBadge";

// Org dashboard (#16). An org-scoped overview: status counts, recent orders, a
// "Needs your sign-off" panel (PENDING escalations targeted at this member — or
// any, for OWNER/ADMIN), and a recent-activity audit feed. The shell (sidebar,
// org switcher, sign-out, create-first-org) lives in layout.tsx.
export const dynamic = "force-dynamic";

// Status families we surface as headline counts (in flight vs. settled).
const ACTIVE_STATUSES = ["DRAFT", "SEARCHING", "ESCALATED", "PURCHASING"] as const;

export default async function DashboardPage() {
  const session = await requireSession();
  const active = await activeOrg(session);
  // Layout guarantees an active org before children render, but guard anyway so
  // the create-first-org path is never broken.
  if (!active) return null;

  // Mandatory org-scope assertion before any org-scoped query.
  await assertOrgAccess(active.orgId);
  const orgId = active.orgId;
  const canManage = canManageOrg(active.role);

  const [
    statusGroups,
    recentOrders,
    signOffEscalations,
    recentEvents,
    memberCount,
  ] = await Promise.all([
    // Order counts by status (org-scoped).
    prisma.order.groupBy({
      by: ["status"],
      where: { orgId },
      _count: { _all: true },
    }),
    // Recent orders.
    prisma.order.findMany({
      where: { orgId },
      orderBy: { createdAt: "desc" },
      take: 6,
      select: {
        id: true,
        title: true,
        brand: true,
        category: true,
        status: true,
        maxBudgetCents: true,
        resultPriceCents: true,
        currency: true,
        createdAt: true,
      },
    }),
    // "Needs your sign-off": PENDING escalations. OWNER/ADMIN see all of them;
    // a plain MEMBER sees only the ones routed to their own membership.
    prisma.escalation.findMany({
      where: {
        orgId,
        status: "PENDING",
        ...(canManage ? {} : { targetMembershipId: active.id }),
      },
      orderBy: { createdAt: "desc" },
      take: 6,
      select: {
        id: true,
        code: true,
        situationText: true,
        suggestedMessage: true,
        proposedValueCents: true,
        urgencyTier: true,
        createdAt: true,
        order: { select: { id: true, title: true, currency: true } },
        targetMembership: {
          select: { user: { select: { name: true, email: true } } },
        },
      },
    }),
    // Recent activity across the org (the audit feed).
    prisma.orderEvent.findMany({
      where: { orgId },
      orderBy: { createdAt: "desc" },
      take: 8,
      select: {
        id: true,
        type: true,
        actorType: true,
        message: true,
        createdAt: true,
        order: { select: { id: true, title: true } },
        actorUser: { select: { name: true, email: true } },
      },
    }),
    prisma.membership.count({ where: { orgId } }),
  ]);

  const countByStatus: Record<string, number> = {};
  let totalOrders = 0;
  for (const g of statusGroups) {
    countByStatus[g.status] = g._count._all;
    totalOrders += g._count._all;
  }
  const activeCount = ACTIVE_STATUSES.reduce(
    (n, s) => n + (countByStatus[s] ?? 0),
    0,
  );
  const completedCount = countByStatus["COMPLETED"] ?? 0;

  const stats = [
    { label: "Total orders", value: totalOrders },
    { label: "In flight", value: activeCount },
    { label: "Needs sign-off", value: signOffEscalations.length },
    { label: "Completed", value: completedCount },
  ];

  return (
    <div>
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-ink/10 pb-6">
        <div>
          <p className="text-sm font-medium uppercase tracking-[0.16em] text-accent">
            {active.org.name}
          </p>
          <h1 className="mt-1.5 text-3xl font-semibold">Dashboard</h1>
          <p className="mt-2 text-sm text-ink/60">
            {memberCount} member{memberCount === 1 ? "" : "s"} · the lay of the land for{" "}
            {active.org.name}.
          </p>
        </div>
        <Link href="/app/orders/new" className="btn-accent shrink-0">
          New order
        </Link>
      </header>

      {/* Headline counts */}
      <div className="mt-8 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {stats.map((s) => (
          <div
            key={s.label}
            className="rounded-xl border border-ink/10 bg-white/50 px-5 py-4"
          >
            <p className="font-display text-3xl font-semibold tabular-nums">
              {s.value}
            </p>
            <p className="mt-1 text-[11px] font-medium uppercase tracking-[0.12em] text-ink/45">
              {s.label}
            </p>
          </div>
        ))}
      </div>

      {/* Needs your sign-off */}
      <section className="mt-10">
        <div className="flex items-baseline justify-between">
          <h2 className="font-display text-xl font-semibold">
            Needs your sign-off
          </h2>
          {!canManage && (
            <span className="text-xs text-ink/45">routed to you</span>
          )}
        </div>
        {signOffEscalations.length === 0 ? (
          <p className="mt-3 rounded-xl border border-dashed border-ink/15 bg-white/40 px-5 py-6 text-sm text-ink/55">
            Nothing waiting on you. The fleet will reach out here the moment a
            purchase needs approval.
          </p>
        ) : (
          <ul className="mt-3 space-y-2">
            {signOffEscalations.map((e) => {
              const orderTitle = e.order?.title ?? "A purchase";
              const target =
                e.targetMembership?.user?.name ??
                e.targetMembership?.user?.email ??
                null;
              const blurb =
                e.suggestedMessage?.trim() || e.situationText?.trim() || "";
              const href = e.order?.id
                ? `/app/orders/${e.order.id}`
                : `/d/${e.code}`;
              return (
                <li key={e.id}>
                  <Link
                    href={href}
                    className="flex items-start gap-4 rounded-xl border border-accent/25 bg-accent/[0.04] px-5 py-4 transition hover:border-accent/50 hover:bg-accent/[0.07]"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium">{orderTitle}</p>
                      {blurb && (
                        <p className="mt-0.5 line-clamp-2 text-xs text-ink/60">
                          {blurb}
                        </p>
                      )}
                      <p className="mt-1 text-[11px] uppercase tracking-[0.1em] text-ink/40">
                        {e.urgencyTier.toLowerCase().replace("_", " ")}
                        {canManage && target ? ` · ${target}` : ""}
                      </p>
                    </div>
                    {e.proposedValueCents != null && (
                      <span className="shrink-0 pt-0.5 text-sm font-medium tabular-nums">
                        {formatCents(e.proposedValueCents, e.order?.currency ?? "EUR")}
                      </span>
                    )}
                    <span className="shrink-0 self-center text-accent">→</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <div className="mt-10 grid gap-8 lg:grid-cols-2">
        {/* Recent orders */}
        <section>
          <div className="flex items-baseline justify-between">
            <h2 className="font-display text-xl font-semibold">Recent orders</h2>
            <Link
              href="/app/orders"
              className="text-sm font-medium text-accent hover:opacity-80"
            >
              All orders →
            </Link>
          </div>
          {recentOrders.length === 0 ? (
            <p className="mt-3 rounded-xl border border-dashed border-ink/15 bg-white/40 px-5 py-6 text-sm text-ink/55">
              No orders yet. Start one and the buyer fleet goes shopping.
            </p>
          ) : (
            <ul className="mt-3 space-y-2">
              {recentOrders.map((o) => (
                <li key={o.id}>
                  <Link
                    href={`/app/orders/${o.id}`}
                    className="flex items-center gap-3 rounded-xl border border-ink/10 bg-white/50 px-4 py-3 transition hover:border-ink/20 hover:bg-white/70"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{o.title}</p>
                      <p className="mt-0.5 truncate text-xs text-ink/45">
                        {o.status === "COMPLETED" && o.resultPriceCents != null
                          ? formatCents(o.resultPriceCents, o.currency)
                          : o.maxBudgetCents != null
                            ? `≤ ${formatCents(o.maxBudgetCents, o.currency)}`
                            : [o.brand, o.category].filter(Boolean).join(" · ") ||
                              "—"}
                      </p>
                    </div>
                    <StatusBadge status={o.status} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Recent activity feed */}
        <section>
          <h2 className="font-display text-xl font-semibold">Recent activity</h2>
          {recentEvents.length === 0 ? (
            <p className="mt-3 rounded-xl border border-dashed border-ink/15 bg-white/40 px-5 py-6 text-sm text-ink/55">
              Activity from your orders shows up here.
            </p>
          ) : (
            <ul className="mt-3 space-y-1">
              {recentEvents.map((ev) => {
                const actor =
                  ev.actorUser?.name ??
                  ev.actorUser?.email ??
                  ev.actorType ??
                  "system";
                return (
                  <li key={ev.id}>
                    <Link
                      href={ev.order?.id ? `/app/orders/${ev.order.id}` : "/app/orders"}
                      className="flex items-start gap-3 rounded-lg px-2 py-2 transition hover:bg-ink/5"
                    >
                      <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-accent/60" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm">
                          <span className="font-medium">{eventLabel(ev.type)}</span>
                          {ev.order?.title ? (
                            <span className="text-ink/55"> · {ev.order.title}</span>
                          ) : null}
                        </p>
                        <p className="mt-0.5 truncate text-xs text-ink/40">
                          {actor} · {timeAgo(ev.createdAt)}
                        </p>
                      </div>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}

// Friendly labels for the audit event types (schema OrderEvent.type values).
const EVENT_LABELS: Record<string, string> = {
  created: "Order created",
  search_started: "Search launched",
  agent_spawned: "Agent spawned",
  candidate_found: "Candidate found",
  escalated: "Escalated for sign-off",
  notified: "Approver notified",
  approved: "Approved",
  declined: "Declined",
  purchased: "Purchased",
  completed: "Completed",
  failed: "Failed",
  note: "Note",
  message: "Message",
};

function eventLabel(type: string): string {
  return EVENT_LABELS[type] ?? type;
}

function timeAgo(date: Date): string {
  const diff = Date.now() - new Date(date).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(date).toLocaleDateString();
}
