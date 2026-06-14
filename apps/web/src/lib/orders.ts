// Order lifecycle helpers — create / append-event / launch. Centralizes the
// writes so the browser API routes, chat intake, and internal endpoints share
// one implementation. Money is integer cents; every write is org-scoped.

import { randomBytes } from "crypto";
import { prisma } from "@/lib/db";
import type { Prisma } from "@prisma/client";
import { resolveFleetTier, fleetTierToN } from "@/lib/fleet-tiers";

export type OrderEventType =
  | "created"
  | "search_started"
  | "agent_spawned"
  | "candidate_found"
  | "supervisor_status"
  | "research_complete"
  | "re_research"
  | "escalated"
  | "notified"
  | "approved"
  | "countered"
  | "declined"
  | "purchased"
  | "completed"
  | "failed"
  | "note"
  | "message";

export type ActorType = "user" | "agent" | "system" | "approver" | "supervisor";

/** Unguessable capability token for /d/:code reply links (24 bytes → 48 hex). */
export function newEscalationCode(): string {
  return randomBytes(24).toString("hex");
}

export interface CreateOrderInput {
  orgId: string;
  requestedById?: string | null;
  title: string;
  description?: string | null;
  category?: string | null;
  brand?: string | null;
  maxBudgetCents?: number | null;
  intakeChannel?: "CHAT" | "VOICE" | "API";
}

/** Create a DRAFT Order + its first "created" audit event in one transaction. */
export async function createOrder(input: CreateOrderInput) {
  const intakeChannel = input.intakeChannel ?? "CHAT";
  const order = await prisma.order.create({
    data: {
      orgId: input.orgId,
      requestedById: input.requestedById ?? null,
      title: input.title.trim() || "Untitled request",
      description: input.description?.trim() || null,
      category: input.category?.trim() || null,
      brand: input.brand?.trim() || null,
      maxBudgetCents:
        input.maxBudgetCents == null ? null : Math.max(0, Math.round(input.maxBudgetCents)),
      intakeChannel,
      status: "DRAFT",
      events: {
        create: {
          orgId: input.orgId,
          type: "created",
          actorType: "user",
          actorUserId: input.requestedById ?? null,
          message: `Order created via ${intakeChannel.toLowerCase()}`,
        },
      },
    },
  });
  return order;
}

/** Append an append-only OrderEvent. Best-effort caller decides on failure. */
export async function appendOrderEvent(params: {
  orderId: string;
  orgId: string;
  type: OrderEventType | string;
  actorType: ActorType | string;
  actorUserId?: string | null;
  message?: string | null;
  data?: Prisma.InputJsonValue | null;
}) {
  return prisma.orderEvent.create({
    data: {
      orderId: params.orderId,
      orgId: params.orgId,
      type: params.type,
      actorType: params.actorType,
      actorUserId: params.actorUserId ?? null,
      message: params.message ?? null,
      data: params.data ?? undefined,
    },
  });
}

/**
 * Launch an order: flip to SEARCHING, append a "search_started" event, and
 * best-effort fire the orchestrator endpoint (only if ORCHESTRATOR_URL is set;
 * never fails the caller if it's unset or unreachable — the event is recorded
 * regardless). The orchestrator is a Modal endpoint whose URL is the complete
 * endpoint (POST to it directly — no /launch suffix). If it returns a
 * missionId, we persist it on the Order so the run ties back to its fleet.
 *
 * Supports re-research: pass `goalOverride` to replace the title/description
 * goal (e.g. a note-refined ask) and `round` to tag which research round this
 * is. When omitted, `round` is read from the order's current `researchRound`.
 *
 * Fleet size: an explicit `opts.fleetTier` (e.g. the picker the user chose at
 * launch) wins; otherwise the order's stored `fleetTier`; otherwise the org's
 * `defaultFleetTier`. The resolved tier is persisted on the order and its agent
 * count flows to the orchestrator (and is echoed on `nAgents`).
 * Returns the updated order.
 */
export async function launchOrder(
  order: {
    id: string;
    orgId: string;
    title: string;
    description: string | null;
    maxBudgetCents?: number | null;
    researchRound?: number | null;
  },
  opts?: { goalOverride?: string | null; round?: number; fleetTier?: string | null },
) {
  // Resolve the fleet size tier → agent count (single source: lib/fleet-tiers).
  const meta = await prisma.order.findUnique({
    where: { id: order.id },
    select: { fleetTier: true, org: { select: { defaultFleetTier: true } } },
  });
  const tier = resolveFleetTier(
    opts?.fleetTier ?? meta?.fleetTier,
    meta?.org?.defaultFleetTier,
  );
  const nAgents = fleetTierToN(tier);

  const updated = await prisma.order.update({
    where: { id: order.id },
    data: { status: "SEARCHING", nAgents, fleetTier: tier },
  });
  await appendOrderEvent({
    orderId: order.id,
    orgId: order.orgId,
    type: "search_started",
    actorType: "system",
    message: "Search launched — dispatching the buyer fleet",
  });

  // Best-effort orchestrator kick. Never throws into the caller.
  const orchestratorUrl = process.env.ORCHESTRATOR_URL;
  if (orchestratorUrl) {
    const goal =
      opts?.goalOverride?.trim() ||
      [order.title, order.description].filter(Boolean).join(" — ");
    const round = opts?.round ?? order.researchRound ?? 0;
    void fireOrchestratorLaunch(orchestratorUrl, {
      orgId: order.orgId,
      orderId: order.id,
      goal,
      n: nAgents,
      budgetCents: order.maxBudgetCents ?? null,
      round,
    });
  }

  return updated;
}

async function fireOrchestratorLaunch(
  endpointUrl: string,
  body: {
    orgId: string;
    orderId: string;
    goal: string;
    n: number;
    budgetCents: number | null;
    round: number;
  },
) {
  try {
    // The Modal endpoint URL is the complete endpoint — POST to it directly.
    const res = await fetch(endpointUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-internal-token": process.env.INTERNAL_API_TOKEN ?? "",
      },
      body: JSON.stringify(body),
      // keep it snappy; the fleet runs async on its own side
      signal: AbortSignal.timeout(8000),
    });
    if (!res.ok) {
      console.warn(`[orders] orchestrator launch non-2xx (${res.status})`);
      return;
    }
    // Capture the returned missionId and tie it to the order.
    const data = (await res.json().catch(() => null)) as
      | { ok?: boolean; missionId?: string; spawnId?: string }
      | null;
    const missionId = data?.missionId;
    if (missionId) {
      await prisma.order
        .update({
          where: { id: body.orderId },
          data: { missionId },
        })
        .catch((err) => {
          console.warn("[orders] failed to persist missionId (ignored):", err);
        });
    }
  } catch (err) {
    console.warn("[orders] orchestrator launch failed (ignored):", err);
  }
}

/** Format integer cents as a localized currency string for UI/audit copy. */
export function formatCents(cents: number | null | undefined, currency = "EUR"): string {
  if (cents == null) return "—";
  return new Intl.NumberFormat("en-IE", {
    style: "currency",
    currency,
  }).format(cents / 100);
}
