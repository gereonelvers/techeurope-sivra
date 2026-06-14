// Resolution write path — the ONE place an escalation gets resolved, shared by:
//   * the public tokenized reply page  /d/:code
//   * the ElevenLabs voice tool         POST /api/voice/resolve
//   * the in-app approver control       (order detail page → POST /d/:code)
//
// It writes the human's resolution + reward signal onto the Escalation, flips
// the Order to its next status, appends an append-only audit OrderEvent, and is
// idempotent: resolving an already-RESOLVED escalation is a no-op that returns
// the existing record. Money is integer cents.

import { prisma } from "@/lib/db";
import type { Prisma } from "@prisma/client";
import { launchOrder } from "@/lib/orders";
import { sanitizeReport, type ResearchReport } from "@/lib/research";

export type ResolutionKind = "approve" | "counter" | "decline";
export type Rating = "good" | "partial" | "wrong";

export interface ResolveInput {
  /** Either the public capability `code` or the cross-service `requestId`. */
  codeOrRequestId: string;
  resolution: ResolutionKind;
  /** Counter / approved value in integer cents. */
  value?: number | null;
  notes?: string | null;
  rating?: Rating | null;
  /** If the router picked the wrong role, the human can correct it. */
  correctedRole?: string | null;
  /** If the router picked the wrong urgency, the human can correct it. */
  correctedUrgency?: string | null;
  /** Human-readable label for who resolved (voice/email path). */
  resolvedByLabel?: string | null;
  /** User id, when resolved by a signed-in member (in-app approver). */
  resolvedById?: string | null;
}

export interface ResolveResult {
  ok: boolean;
  alreadyResolved: boolean;
  escalation: {
    id: string;
    requestId: string;
    orderId: string | null;
    orgId: string;
    status: string;
    resolution: string | null;
    resolvedValueCents: number | null;
    rewardScalar: number | null;
    latencyMs: number | null;
    resolvedAt: Date | null;
  };
  orderStatus?: string;
}

/** What the counter re-research kick needs, captured inside the transaction and
 * consumed after it commits. */
interface ReResearchPayload {
  orderId: string;
  orgId: string;
  title: string;
  description: string | null;
  maxBudgetCents: number | null;
  researchRound: number;
  refinedGoal: string;
}

/** Sentinel thrown when no Escalation matches the code/requestId. */
export class EscalationNotFoundError extends Error {
  status = 404 as const;
  constructor(message = "Escalation not found") {
    super(message);
    this.name = "EscalationNotFoundError";
  }
}

const VALID_RESOLUTIONS = new Set<ResolutionKind>(["approve", "counter", "decline"]);
const VALID_RATINGS = new Set<Rating>(["good", "partial", "wrong"]);

/**
 * Reward scalar from the human's feedback (beat #3 learning signal):
 *   base: good = +1, partial = 0, wrong = −1 (no rating ⇒ 0 base)
 *   −0.3 for each of corrected role / corrected urgency
 *   clamped to [−2, 1]
 */
export function computeRewardScalar(
  rating: Rating | null | undefined,
  correctedRole: string | null | undefined,
  correctedUrgency: string | null | undefined,
): number {
  let reward = 0;
  if (rating === "good") reward = 1;
  else if (rating === "partial") reward = 0;
  else if (rating === "wrong") reward = -1;

  if (correctedRole) reward -= 0.3;
  if (correctedUrgency) reward -= 0.3;

  return Math.max(-2, Math.min(1, reward));
}

/**
 * Map a resolution to the Order status it drives toward (RESEARCH-FLOW.md §4):
 *   approve  → COMPLETED (buy the report's bestCandidate / countered value)
 *   decline  → CANCELLED
 *   counter  → SEARCHING (RE-RESEARCH: re-launch the fleet with a refined goal)
 * The transaction sets the immediate status; the re-research kick happens after
 * the transaction (it does I/O), best-effort.
 */
function nextOrderStatus(
  resolution: ResolutionKind,
): "COMPLETED" | "CANCELLED" | "SEARCHING" {
  if (resolution === "decline") return "CANCELLED";
  if (resolution === "counter") return "SEARCHING";
  return "COMPLETED";
}

/**
 * Resolve an escalation. Idempotent on an already-resolved escalation. Throws
 * EscalationNotFoundError if nothing matches. All writes happen in a single
 * transaction so the Escalation, Order, and audit event move together.
 */
export async function resolveEscalation(input: ResolveInput): Promise<ResolveResult> {
  const resolution = input.resolution;
  if (!VALID_RESOLUTIONS.has(resolution)) {
    throw new Error(`invalid resolution: ${resolution}`);
  }
  const rating =
    input.rating && VALID_RATINGS.has(input.rating) ? input.rating : null;

  const key = input.codeOrRequestId;
  const existing = await prisma.escalation.findFirst({
    where: { OR: [{ code: key }, { requestId: key }] },
  });
  if (!existing) throw new EscalationNotFoundError();

  // Idempotency: already resolved → return as-is, no further writes.
  if (existing.status === "RESOLVED") {
    let orderStatus: string | undefined;
    if (existing.orderId) {
      const o = await prisma.order.findUnique({
        where: { id: existing.orderId },
        select: { status: true },
      });
      orderStatus = o?.status;
    }
    return {
      ok: true,
      alreadyResolved: true,
      escalation: {
        id: existing.id,
        requestId: existing.requestId,
        orderId: existing.orderId,
        orgId: existing.orgId,
        status: existing.status,
        resolution: existing.resolution,
        resolvedValueCents: existing.resolvedValueCents,
        rewardScalar: existing.rewardScalar,
        latencyMs: existing.latencyMs,
        resolvedAt: existing.resolvedAt,
      },
      orderStatus,
    };
  }

  const resolvedAt = new Date();
  const latencyMs = Math.max(0, resolvedAt.getTime() - existing.createdAt.getTime());
  const rewardScalar = computeRewardScalar(
    rating,
    input.correctedRole ?? null,
    input.correctedUrgency ?? null,
  );
  const value =
    input.value === undefined || input.value === null
      ? null
      : Math.round(Number(input.value));

  // Carries the bits the post-transaction re-research kick needs (counter path).
  let reResearch: ReResearchPayload | null = null;

  const updated = await prisma.$transaction(async (tx) => {
    const esc = await tx.escalation.update({
      where: { id: existing.id },
      data: {
        status: "RESOLVED",
        resolution,
        resolvedValueCents: value,
        notes: input.notes ?? null,
        rating,
        correctedRole: input.correctedRole ?? null,
        correctedUrgency: input.correctedUrgency ?? null,
        rewardScalar,
        latencyMs,
        resolvedAt,
        resolvedByLabel: input.resolvedByLabel ?? null,
        resolvedById: input.resolvedById ?? null,
      },
    });

    if (esc.orderId) {
      const order = await tx.order.findUnique({
        where: { id: esc.orderId },
        select: {
          status: true,
          title: true,
          description: true,
          maxBudgetCents: true,
          researchRound: true,
          report: true,
        },
      });

      // Decision audit event (which way the human went).
      await tx.orderEvent.create({
        data: {
          orderId: esc.orderId,
          orgId: esc.orgId,
          type:
            resolution === "decline"
              ? "declined"
              : resolution === "counter"
                ? "countered"
                : "approved",
          actorType: "approver",
          actorUserId: input.resolvedById ?? null,
          message:
            resolution === "decline"
              ? `Declined by ${input.resolvedByLabel ?? "approver"}`
              : `${resolution === "counter" ? "Countered" : "Approved"} by ${
                  input.resolvedByLabel ?? "approver"
                }${value != null ? ` at €${(value / 100).toFixed(2)}` : ""}`,
          data: {
            resolution,
            value,
            rating,
            correctedRole: input.correctedRole ?? null,
            correctedUrgency: input.correctedUrgency ?? null,
            rewardScalar,
          },
        },
      });

      const report = order?.report ? sanitizeReport(order.report) : null;

      if (resolution === "decline") {
        // Decline → CANCELLED (terminal).
        if (order && order.status !== "CANCELLED") {
          await tx.order.update({
            where: { id: esc.orderId },
            data: { status: "CANCELLED" },
          });
        }
      } else if (resolution === "counter") {
        // Counter → RE-RESEARCH. Bump researchRound, flip to SEARCHING, append a
        // "re_research" event carrying the refined ask. The fleet re-launch
        // happens after the transaction (network I/O), best-effort.
        if (order && order.status !== "COMPLETED" && order.status !== "CANCELLED") {
          const nextRound = (order.researchRound ?? 0) + 1;
          const refinedGoal = buildRefinedGoal(order, report, value, input.notes);
          await tx.order.update({
            where: { id: esc.orderId },
            data: { status: "SEARCHING", researchRound: nextRound },
          });
          await tx.orderEvent.create({
            data: {
              orderId: esc.orderId,
              orgId: esc.orgId,
              type: "re_research",
              actorType: "supervisor",
              message: refinedGoal,
              data: {
                round: nextRound,
                counterValueCents: value,
                note: input.notes ?? null,
                escalationId: esc.id,
              },
            },
          });
          reResearch = {
            orderId: esc.orderId,
            orgId: esc.orgId,
            title: order.title,
            description: order.description,
            // A counter value re-sets the budget for the new round.
            maxBudgetCents: value ?? order.maxBudgetCents,
            researchRound: nextRound,
            refinedGoal,
          };
        }
      } else {
        // Approve → COMPLETED, buying the report's bestCandidate (or the
        // countered/proposed value). Idempotent: never re-complete.
        if (order && order.status !== "COMPLETED") {
          const best = report?.bestCandidate ?? null;
          const resultPriceCents =
            value ??
            best?.priceCents ??
            existing.proposedValueCents ??
            order.maxBudgetCents ??
            null;
          const resultTitle =
            best?.title?.trim() || existing.situationText?.trim() || order.title;
          await tx.order.update({
            where: { id: esc.orderId },
            data: {
              status: "COMPLETED",
              completedAt: resolvedAt,
              resultTitle,
              resultPriceCents,
              receipt: {
                approvedBy: input.resolvedByLabel ?? "approver",
                resolvedValueCents: resultPriceCents,
                escalationId: esc.id,
                candidate: best ?? undefined,
                note: "Approved via delegation",
              } as unknown as Prisma.InputJsonValue,
            },
          });
          await tx.orderEvent.create({
            data: {
              orderId: esc.orderId,
              orgId: esc.orgId,
              type: "completed",
              actorType: "system",
              message: `Order completed${
                resultPriceCents != null
                  ? ` at €${(resultPriceCents / 100).toFixed(2)}`
                  : ""
              }`,
              data: {
                resultTitle,
                resultPriceCents,
                escalationId: esc.id,
              },
            },
          });
        }
      }
    }

    return esc;
  });

  // Best-effort re-research kick (counter path) — outside the transaction so
  // the orchestrator I/O never holds a DB connection or fails the resolution.
  if (reResearch) {
    const rr: ReResearchPayload = reResearch;
    try {
      await launchOrder(
        {
          id: rr.orderId,
          orgId: rr.orgId,
          title: rr.title,
          description: rr.description,
          maxBudgetCents: rr.maxBudgetCents,
          researchRound: rr.researchRound,
        },
        { goalOverride: rr.refinedGoal, round: rr.researchRound },
      );
    } catch (err) {
      console.warn("[resolve] re-research launch failed (ignored):", err);
    }
  }

  const finalOrderStatus = updated.orderId
    ? resolution === "decline"
      ? "CANCELLED"
      : resolution === "counter"
        ? "SEARCHING"
        : "COMPLETED"
    : undefined;

  return {
    ok: true,
    alreadyResolved: false,
    escalation: {
      id: updated.id,
      requestId: updated.requestId,
      orderId: updated.orderId,
      orgId: updated.orgId,
      status: updated.status,
      resolution: updated.resolution,
      resolvedValueCents: updated.resolvedValueCents,
      rewardScalar: updated.rewardScalar,
      latencyMs: updated.latencyMs,
      resolvedAt: updated.resolvedAt,
    },
    orderStatus: finalOrderStatus,
  };
}

/** Refine the research goal for a counter re-research from the report + note +
 * counter value. Mirrors the example in RESEARCH-FLOW.md ("…over budget → try
 * X"). Best-effort string assembly; always returns something sensible. */
function buildRefinedGoal(
  order: { title: string; description: string | null },
  report: ResearchReport | null,
  counterValueCents: number | null,
  notes: string | null | undefined,
): string {
  const parts: string[] = [];
  const base = [order.title, order.description].filter(Boolean).join(" — ");
  parts.push(base || order.title);
  if (counterValueCents != null) {
    parts.push(`new budget €${(counterValueCents / 100).toFixed(2)}`);
  }
  if (notes?.trim()) {
    parts.push(notes.trim());
  } else if (report?.bestCandidate) {
    parts.push(`previous best was ${report.bestCandidate.title} at €${(report.bestCandidate.priceCents / 100).toFixed(2)} — find something cheaper / different`);
  }
  return parts.join(" — ");
}

/**
 * Shape an Escalation row as a HumanResolution (the contract the Python fleet
 * polls for via GET /api/internal/escalations/:requestId/resolution). Field
 * names mirror shared/contracts/schema.py HumanResolution.
 */
export function toHumanResolution(esc: {
  requestId: string;
  resolution: string | null;
  resolvedValueCents: number | null;
  notes: string | null;
  latencyMs: number | null;
  rating: string | null;
  correctedRole: string | null;
  correctedUrgency: string | null;
  resolvedByLabel: string | null;
  resolvedAt: Date | null;
}) {
  return {
    request_id: esc.requestId,
    resolved_by: esc.resolvedByLabel ?? "unknown",
    resolution: esc.resolution ?? "approve",
    // schema.py carries money as euros (float); cents → euros for the contract.
    value:
      esc.resolvedValueCents == null ? null : esc.resolvedValueCents / 100,
    notes: esc.notes,
    latency_ms: esc.latencyMs ?? 0,
    rating: esc.rating,
    corrected_person: esc.correctedRole,
    corrected_urgency: esc.correctedUrgency,
    resolved_at: (esc.resolvedAt ?? new Date()).toISOString(),
  };
}
