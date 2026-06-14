import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { assertInternal, InternalAuthError } from "@/lib/internal";
import { buildPolicyPayload } from "@/lib/policy";
import { appendOrderEvent, newEscalationCode } from "@/lib/orders";
import { notifyEscalation, type DispatchResult } from "@/lib/dispatch";
import { getActiveRouterModel } from "@/lib/router_config";
import { sanitizeReport, type ResearchReport } from "@/lib/research";
import type { Prisma } from "@prisma/client";

// POST /api/internal/orders/:id/research { report: ResearchReport }
//
// The supervisor (Gemini), after orchestrating the browsing fleet, posts the
// aggregated ResearchReport here. This is the SEAM where research ends and the
// app's escalate-vs-auto-buy decision begins (RESEARCH-FLOW.md):
//
//   1. Store the report on Order.report; append "research_complete"
//      (actorType:"supervisor").
//   2. AUTO-BUY when report.found && report.inBudget AND the order's requester
//      is authorized — their Membership.approvalLimitCents (for this org) is
//      null/∞ OR >= bestCandidate.priceCents. Complete the order; no human.
//   3. ELSE ESCALATE: build a DecisionRequest from the report, call the
//      supervisor POST /route with the org policy, create ONE Escalation
//      (carrying the report), flip the order to ESCALATED, dispatch.
//
// Idempotent per round: if a report for this round was already processed (the
// order has moved past SEARCHING for this round, or an escalation already
// carries this round's report), it returns the prior outcome without
// re-deciding.
const SUPERVISOR_URL = process.env.SUPERVISOR_URL || "https://sivra.io";

interface ResearchBody {
  report?: unknown;
}

export async function POST(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  try {
    assertInternal(req);
  } catch (err) {
    if (err instanceof InternalAuthError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }

  const order = await prisma.order.findUnique({
    where: { id: params.id },
    select: {
      id: true,
      orgId: true,
      title: true,
      status: true,
      maxBudgetCents: true,
      currency: true,
      researchRound: true,
      requestedById: true,
      report: true,
    },
  });
  if (!order) {
    return NextResponse.json({ error: "Order not found" }, { status: 404 });
  }

  const body = (await req.json().catch(() => ({}))) as ResearchBody;
  const report = sanitizeReport(body.report);

  // ── Idempotency ───────────────────────────────────────────────────────────
  // If we already have an escalation carrying THIS round's report, or the order
  // already completed/escalated and the stored report is for this same round,
  // we've processed it — return the current outcome without re-deciding.
  const existingEsc = await prisma.escalation.findFirst({
    where: {
      orderId: order.id,
      guardrail: { path: ["researchRound"], equals: report.round },
    },
    select: { id: true, code: true, requestId: true },
  });
  if (existingEsc) {
    return NextResponse.json(
      { ok: true, decision: "escalate", alreadyProcessed: true, escalationId: existingEsc.id },
      { status: 200 },
    );
  }
  const storedRound = readStoredRound(order.report);
  if (
    storedRound === report.round &&
    (order.status === "COMPLETED" || order.status === "ESCALATED")
  ) {
    return NextResponse.json(
      { ok: true, decision: order.status === "COMPLETED" ? "auto_buy" : "escalate", alreadyProcessed: true },
      { status: 200 },
    );
  }

  // ── 1. Store the report + append research_complete ────────────────────────
  await prisma.order.update({
    where: { id: order.id },
    data: { report: report as unknown as Prisma.InputJsonValue, researchRound: report.round },
  });
  await appendOrderEvent({
    orderId: order.id,
    orgId: order.orgId,
    type: "research_complete",
    actorType: "supervisor",
    message: report.summary || (report.found ? "Research complete" : "No in-budget match found"),
    data: report as unknown as Prisma.InputJsonValue,
  }).catch(() => {});

  // ── 2. Decide: AUTO-BUY vs ESCALATE ───────────────────────────────────────
  const best = report.bestCandidate;
  const requesterLimit = await requesterApprovalLimit(order.orgId, order.requestedById);
  const requesterAuthorized =
    requesterLimit == null || (best != null && requesterLimit >= best.priceCents);

  const canAutoBuy = report.found && report.inBudget && best != null && requesterAuthorized;

  if (canAutoBuy) {
    return await autoBuy(order, report, best!);
  }

  return await escalate(order, report);
}

// ── Auto-buy: complete the order from the best candidate, no human ────────────
async function autoBuy(
  order: { id: string; orgId: string },
  report: ResearchReport,
  best: NonNullable<ResearchReport["bestCandidate"]>,
) {
  const receipt = {
    autoBought: true,
    candidate: best,
    note: "Auto-bought — within budget & requester authorized",
  };

  await prisma.$transaction(async (tx) => {
    await tx.order.update({
      where: { id: order.id },
      data: {
        status: "COMPLETED",
        completedAt: new Date(),
        resultTitle: best.title,
        resultPriceCents: best.priceCents,
        receipt: receipt as unknown as Prisma.InputJsonValue,
      },
    });
    await tx.orderEvent.create({
      data: {
        orderId: order.id,
        orgId: order.orgId,
        type: "purchased",
        actorType: "supervisor",
        message: `Auto-bought ${best.title} for €${(best.priceCents / 100).toFixed(2)} — within budget & requester authorized`,
        data: { candidate: best, autoBought: true } as unknown as Prisma.InputJsonValue,
      },
    });
    await tx.orderEvent.create({
      data: {
        orderId: order.id,
        orgId: order.orgId,
        type: "completed",
        actorType: "system",
        message: `Order completed at €${(best.priceCents / 100).toFixed(2)}`,
        data: { resultTitle: best.title, resultPriceCents: best.priceCents } as unknown as Prisma.InputJsonValue,
      },
    });
  });

  return NextResponse.json(
    {
      ok: true,
      decision: "auto_buy",
      resultTitle: best.title,
      resultPriceCents: best.priceCents,
    },
    { status: 200 },
  );
}

// ── Escalate: route via the supervisor, create ONE escalation, dispatch ───────
async function escalate(
  order: {
    id: string;
    orgId: string;
    title: string;
    maxBudgetCents: number | null;
    researchRound: number;
  },
  report: ResearchReport,
) {
  const best = report.bestCandidate;
  const requestId = `research-${order.id}-r${report.round}`;
  const code = newEscalationCode();

  const proposedValueCents = best?.priceCents ?? null;
  const budgetCapCents = order.maxBudgetCents ?? null;
  const decisionType = report.found
    ? report.inBudget
      ? "approve_purchase"
      : "price_over_budget"
    : "no_match_found";
  const situationText =
    report.summary ||
    (report.found
      ? "A matching item was found and needs sign-off."
      : "No in-budget match — needs guidance.");

  // Idempotency on requestId (unique). If we've already created it, return it.
  const prior = await prisma.escalation.findUnique({ where: { requestId } });
  if (prior) {
    return NextResponse.json(
      { ok: true, decision: "escalate", alreadyProcessed: true, escalationId: prior.id },
      { status: 200 },
    );
  }

  // Create the PENDING escalation carrying the report (on guardrail.report).
  const escalation = await prisma.escalation.create({
    data: {
      orgId: order.orgId,
      orderId: order.id,
      requestId,
      code,
      decisionType,
      situationText,
      proposedValueCents,
      budgetCapCents,
      agentConfidence: report.found ? 0.75 : 0.4,
      guardrail: {
        researchRound: report.round,
        report: report,
      } as unknown as Prisma.InputJsonValue,
    },
  });

  // Call the stateless supervisor /route with the org policy + active model.
  const policy = await buildPolicyPayload(order.orgId);
  const activeModelId = await getActiveRouterModel().catch(() => null);
  const decisionRequest = {
    request_id: requestId,
    org_id: order.orgId,
    decision_type: decisionType,
    situation_text: situationText,
    proposed_value: proposedValueCents == null ? null : proposedValueCents / 100,
    budget_cap: budgetCapCents == null ? null : budgetCapCents / 100,
    agent_confidence: report.found ? 0.75 : 0.4,
    item: best
      ? {
          title: best.title,
          listed_price: best.priceCents / 100,
          currency: "EUR",
          item_id: null,
          url: best.url ?? null,
        }
      : null,
  };

  let routing: RouteResult | null = null;
  try {
    const res = await fetch(`${SUPERVISOR_URL.replace(/\/$/, "")}/route`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request: decisionRequest, policy, model: activeModelId ?? undefined }),
      signal: AbortSignal.timeout(15000),
    });
    if (res.ok) {
      routing = (await res.json()) as RouteResult;
    } else {
      const detail = await res.text().catch(() => "");
      console.warn(`[research] supervisor /route non-2xx (${res.status}): ${detail}`);
    }
  } catch (err) {
    console.warn("[research] supervisor /route failed:", err);
  }

  const urgencyTier = mapUrgency(routing?.urgency_tier);
  const targetPurchasingRole = routing?.target_purchasing_role ?? null;
  let targetMembershipId = routing?.target_membership_id ?? null;
  if (targetMembershipId) {
    const m = await prisma.membership.findFirst({
      where: { id: targetMembershipId, orgId: order.orgId },
      select: { id: true },
    });
    if (!m) targetMembershipId = null;
  }

  const updated = await prisma.escalation.update({
    where: { id: escalation.id },
    data: {
      shouldDelegate: routing?.should_delegate ?? true,
      targetPurchasingRole,
      targetMembershipId,
      urgencyTier,
      suggestedMessage: routing?.suggested_message ?? situationText,
      routerVersion: routing?.model_version ?? null,
      routing: (routing as unknown as object) ?? undefined,
    },
  });

  // Flip the order → ESCALATED + audit.
  await prisma.order.update({
    where: { id: order.id },
    data: { status: "ESCALATED" },
  });
  await appendOrderEvent({
    orderId: order.id,
    orgId: order.orgId,
    type: "escalated",
    actorType: "supervisor",
    message: updated.suggestedMessage ?? situationText,
    data: {
      requestId,
      decisionType,
      proposedValueCents,
      budgetCapCents,
      targetPurchasingRole,
      urgencyTier,
      code,
      researchRound: report.round,
    },
  }).catch(() => {});

  // Dispatch to the resolved target (best-effort) + audit "notified".
  let targetMember: {
    user: { email: string | null; phone: string | null; name: string | null };
  } | null = null;
  if (targetMembershipId) {
    targetMember = await prisma.membership.findUnique({
      where: { id: targetMembershipId },
      select: { user: { select: { email: true, phone: true, name: true } } },
    });
  }

  let dispatchResults: DispatchResult[] = [];
  if (updated.shouldDelegate) {
    try {
      dispatchResults = await notifyEscalation(
        {
          code,
          requestId,
          urgencyTier,
          suggestedMessage: updated.suggestedMessage,
          situationText,
          orderTitle: order.title,
          targetPurchasingRole,
        },
        targetMember
          ? {
              email: targetMember.user.email,
              phone: targetMember.user.phone,
              name: targetMember.user.name,
            }
          : null,
      );
    } catch (err) {
      console.warn("[research] dispatch failed:", err);
    }
    await appendOrderEvent({
      orderId: order.id,
      orgId: order.orgId,
      type: "notified",
      actorType: "system",
      message: `Notified ${targetPurchasingRole ?? "approver"} (${urgencyTier.toLowerCase()})`,
      data: {
        urgencyTier,
        targetMembershipId,
        dispatch: dispatchResults.map((d) => ({
          channel: d.channel,
          ok: d.ok,
          dryRun: d.dryRun,
          ...(d.detail ? { detail: d.detail } : {}),
        })),
      },
    }).catch(() => {});
  }

  return NextResponse.json(
    {
      ok: true,
      decision: "escalate",
      escalationId: updated.id,
      code,
      targetPurchasingRole,
      urgencyTier,
    },
    { status: 201 },
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** The order requester's approvalLimitCents for this org (null = unlimited/∞,
 * or no requester / no membership → treat as unlimited so a requesterless order
 * isn't blocked by the auto-buy gate when it's in budget). */
async function requesterApprovalLimit(
  orgId: string,
  requestedById: string | null,
): Promise<number | null> {
  if (!requestedById) return null;
  const m = await prisma.membership.findUnique({
    where: { orgId_userId: { orgId, userId: requestedById } },
    select: { approvalLimitCents: true },
  });
  if (!m) return null;
  return m.approvalLimitCents ?? null;
}

function readStoredRound(report: unknown): number | null {
  if (!report || typeof report !== "object") return null;
  const r = (report as Record<string, unknown>).round;
  return typeof r === "number" ? r : null;
}

interface RouteResult {
  request_id: string;
  should_delegate: boolean;
  target_person?: string;
  target_purchasing_role?: string | null;
  target_membership_id?: string | null;
  urgency_tier: string;
  suggested_message: string;
  model_version?: string;
}

function mapUrgency(u: string | undefined): "ASYNC" | "URGENT_PUSH" | "VOICE" {
  switch ((u ?? "").toLowerCase()) {
    case "voice":
      return "VOICE";
    case "urgent_push":
      return "URGENT_PUSH";
    default:
      return "ASYNC";
  }
}
