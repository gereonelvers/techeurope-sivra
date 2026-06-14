import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { assertInternal, InternalAuthError } from "@/lib/internal";
import { buildPolicyPayload } from "@/lib/policy";
import { newEscalationCode, appendOrderEvent } from "@/lib/orders";
import { notifyEscalation, type DispatchResult } from "@/lib/dispatch";
import { getActiveRouterModel } from "@/lib/router_config";

// POST /api/internal/escalations — the fleet's escalation entrypoint (replaces
// the supervisor's own /escalate). Called by the Python orchestrator with the
// shared x-internal-token. It:
//   1. creates an Escalation(PENDING) with a random unguessable `code`,
//   2. calls the stateless supervisor POST /route with the org policy,
//   3. stores the RoutingDecision fields,
//   4. flips the Order → ESCALATED + appends "escalated",
//   5. dispatches the notification to the resolved target + appends "notified",
//   6. returns the RoutingDecision JSON.
//
// Body: { requestId, orgId, orderId?, decisionType, situationText,
//         proposedValueCents?, budgetCapCents?, agentConfidence?, item? }
const SUPERVISOR_URL = process.env.SUPERVISOR_URL || "https://sivra.io";

interface EscalationBody {
  requestId?: string;
  orgId?: string;
  orderId?: string | null;
  decisionType?: string;
  situationText?: string;
  proposedValueCents?: number | null;
  budgetCapCents?: number | null;
  agentConfidence?: number | null;
  item?: {
    title?: string;
    listed_price?: number | null;
    currency?: string;
    item_id?: number | null;
    url?: string | null;
  } | null;
}

export async function POST(req: NextRequest) {
  try {
    assertInternal(req);
  } catch (err) {
    if (err instanceof InternalAuthError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }

  const body = (await req.json().catch(() => ({}))) as EscalationBody;
  const requestId = String(body.requestId ?? "").trim();
  const orgId = String(body.orgId ?? "").trim();
  const decisionType = String(body.decisionType ?? "").trim();
  const situationText = String(body.situationText ?? "").trim();
  if (!requestId || !orgId || !decisionType || !situationText) {
    return NextResponse.json(
      { error: "requestId, orgId, decisionType, situationText are required" },
      { status: 400 },
    );
  }

  // Verify the org exists (defensive — internal callers are trusted but typos happen).
  const org = await prisma.organization.findUnique({
    where: { id: orgId },
    select: { id: true },
  });
  if (!org) {
    return NextResponse.json({ error: "Unknown orgId" }, { status: 404 });
  }

  // Validate the order (if any) belongs to this org.
  let orderId: string | null = body.orderId ?? null;
  let orderTitle: string | null = null;
  if (orderId) {
    const order = await prisma.order.findUnique({
      where: { id: orderId },
      select: { id: true, orgId: true, title: true },
    });
    if (!order || order.orgId !== orgId) {
      orderId = null; // ignore a mismatched order rather than fail the escalation
    } else {
      orderTitle = order.title;
    }
  }

  // Idempotency: requestId is unique. If we've seen it, return the stored routing.
  const existing = await prisma.escalation.findUnique({
    where: { requestId },
  });
  if (existing) {
    return NextResponse.json(buildRoutingResponse(existing), { status: 200 });
  }

  // 1. Create the PENDING escalation with an unguessable capability code.
  const code = newEscalationCode();
  const proposedValueCents =
    body.proposedValueCents == null ? null : Math.round(body.proposedValueCents);
  const budgetCapCents =
    body.budgetCapCents == null ? null : Math.round(body.budgetCapCents);
  const agentConfidence =
    typeof body.agentConfidence === "number" ? body.agentConfidence : null;

  const escalation = await prisma.escalation.create({
    data: {
      orgId,
      orderId,
      requestId,
      code,
      decisionType,
      situationText,
      proposedValueCents,
      budgetCapCents,
      agentConfidence,
    },
  });

  // 2. Call the stateless supervisor /route with the org policy + the DB-backed
  //    active router model (promotion is a no-redeploy DB write — see
  //    lib/router_config.ts). The supervisor binds a PioneerRouter to this model.
  const policy = await buildPolicyPayload(orgId);
  const activeModelId = await getActiveRouterModel();
  const decisionRequest = {
    request_id: requestId,
    org_id: orgId,
    decision_type: decisionType,
    situation_text: situationText,
    // schema.py carries money as euros (float); cents → euros.
    proposed_value: proposedValueCents == null ? null : proposedValueCents / 100,
    budget_cap: budgetCapCents == null ? null : budgetCapCents / 100,
    agent_confidence: agentConfidence ?? 0.5,
    item: body.item
      ? {
          title: body.item.title ?? "",
          listed_price: body.item.listed_price ?? null,
          currency: body.item.currency ?? "EUR",
          item_id: body.item.item_id ?? null,
          url: body.item.url ?? null,
        }
      : null,
  };

  let routing: RouteResult | null = null;
  try {
    const res = await fetch(`${SUPERVISOR_URL.replace(/\/$/, "")}/route`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request: decisionRequest, policy, model: activeModelId }),
      signal: AbortSignal.timeout(15000),
    });
    if (res.ok) {
      routing = (await res.json()) as RouteResult;
    } else {
      const detail = await res.text().catch(() => "");
      console.warn(`[escalations] supervisor /route non-2xx (${res.status}): ${detail}`);
    }
  } catch (err) {
    console.warn("[escalations] supervisor /route failed:", err);
  }

  // 3. Store the RoutingDecision (best-effort defaults if /route was unreachable).
  const urgencyTier = mapUrgency(routing?.urgency_tier);
  const targetPurchasingRole = routing?.target_purchasing_role ?? null;
  let targetMembershipId = routing?.target_membership_id ?? null;
  // Guard: only persist a membership id that actually exists in this org.
  if (targetMembershipId) {
    const m = await prisma.membership.findFirst({
      where: { id: targetMembershipId, orgId },
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
      guardrail: (routing?.guardrail as unknown as object) ?? undefined,
    },
  });

  // 4. Flip the order → ESCALATED + audit.
  if (orderId) {
    await prisma.order.update({
      where: { id: orderId },
      data: { status: "ESCALATED" },
    });
    await appendOrderEvent({
      orderId,
      orgId,
      type: "escalated",
      actorType: "agent",
      message: routing?.suggested_message ?? situationText,
      data: {
        requestId,
        decisionType,
        proposedValueCents,
        budgetCapCents,
        targetPurchasingRole,
        urgencyTier,
        code,
      },
    }).catch(() => {});
  }

  // 5. Dispatch to the resolved target member (best-effort) + audit "notified".
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
          orderTitle,
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
      console.warn("[escalations] dispatch failed:", err);
    }
    if (orderId) {
      await appendOrderEvent({
        orderId,
        orgId,
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
  }

  return NextResponse.json(buildRoutingResponse(updated), { status: 201 });
}

interface RouteResult {
  request_id: string;
  should_delegate: boolean;
  target_person?: string;
  target_purchasing_role?: string | null;
  target_membership_id?: string | null;
  urgency_tier: string;
  suggested_message: string;
  rationale?: string;
  model_version?: string;
  guardrail?: unknown;
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

/** Rebuild a RoutingDecision-shaped response from a stored Escalation row. */
function buildRoutingResponse(esc: {
  requestId: string;
  shouldDelegate: boolean;
  targetPurchasingRole: string | null;
  targetMembershipId: string | null;
  urgencyTier: string;
  suggestedMessage: string | null;
  routerVersion: string | null;
  routing: unknown;
  guardrail: unknown;
  code: string;
}) {
  // Prefer the stored full routing JSON if present; else synthesize the contract.
  const stored = esc.routing as Record<string, unknown> | null;
  if (stored && typeof stored === "object" && "request_id" in stored) {
    return { ...stored, code: esc.code };
  }
  return {
    request_id: esc.requestId,
    should_delegate: esc.shouldDelegate,
    target_person: esc.targetPurchasingRole ?? "none",
    target_purchasing_role: esc.targetPurchasingRole,
    target_membership_id: esc.targetMembershipId,
    urgency_tier: esc.urgencyTier.toLowerCase(),
    suggested_message: esc.suggestedMessage ?? "",
    model_version: esc.routerVersion ?? "unknown",
    guardrail: esc.guardrail ?? null,
    code: esc.code,
  };
}
