import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import {
  requireSession,
  activeOrg,
  UnauthorizedError,
  ForbiddenError,
} from "@/lib/org";

// GET /api/routing — everything the decision-routing map needs for the active
// org: team members (by purchasing role), the policy's budget bands, and the
// recent escalations (the "live actions"). Polled by the RoutingMap component.
export const dynamic = "force-dynamic";
export const revalidate = 0;

interface Rule {
  maxBudgetCents: number | null;
  targetPurchasingRole: string | null;
  urgency: string | null;
  autoApprove?: boolean;
}

export async function GET() {
  try {
    const session = await requireSession();
    const active = await activeOrg(session);
    if (!active) return NextResponse.json({ error: "No active org" }, { status: 400 });
    const orgId = active.orgId;

    const [memberships, policy, escalations] = await Promise.all([
      prisma.membership.findMany({
        where: { orgId },
        orderBy: { createdAt: "asc" },
        select: {
          id: true,
          purchasingRole: true,
          approvalLimitCents: true,
          role: true,
          user: { select: { name: true, email: true, phoneVerifiedAt: true } },
        },
      }),
      prisma.permissionPolicy.findFirst({
        where: { orgId },
        orderBy: [{ isDefault: "desc" }, { createdAt: "asc" }],
      }),
      prisma.escalation.findMany({
        where: { orgId },
        orderBy: { createdAt: "desc" },
        take: 14,
        select: {
          id: true,
          proposedValueCents: true,
          decisionType: true,
          targetPurchasingRole: true,
          urgencyTier: true,
          status: true,
          resolution: true,
          resolvedByLabel: true,
          situationText: true,
          suggestedMessage: true,
          createdAt: true,
          resolvedAt: true,
          order: { select: { id: true, title: true, currency: true } },
          targetMembership: { select: { user: { select: { name: true, email: true } } } },
        },
      }),
    ]);

    const nameOf = (u?: { name: string | null; email: string | null } | null) =>
      u?.name || u?.email?.split("@")[0] || null;

    const members = memberships.map((m) => ({
      id: m.id,
      name: nameOf(m.user) ?? "—",
      role: m.purchasingRole,
      approvalLimitCents: m.approvalLimitCents,
      phoneVerified: !!m.user?.phoneVerifiedAt,
      orgRole: m.role,
    }));

    const rules: Rule[] = Array.isArray(policy?.rules)
      ? (policy!.rules as unknown as Rule[])
      : [];
    const autoApproveMaxCents = policy?.autoApproveMaxCents ?? 5000;

    // Ordered budget bands: auto-buy first, then each policy rule as a band with
    // a [lower, upper] range (lower = previous band's upper).
    let lower = 0;
    const bands: Array<{
      kind: "auto" | "human";
      lowerCents: number;
      maxCents: number | null;
      role: string | null;
      urgency: string | null;
    }> = [
      { kind: "auto", lowerCents: 0, maxCents: autoApproveMaxCents, role: null, urgency: null },
    ];
    lower = autoApproveMaxCents;
    for (const r of rules) {
      bands.push({
        kind: "human",
        lowerCents: lower,
        maxCents: r.maxBudgetCents,
        role: r.targetPurchasingRole,
        urgency: r.urgency,
      });
      lower = r.maxBudgetCents ?? lower;
    }

    const escs = escalations.map((e) => ({
      id: e.id,
      proposedValueCents: e.proposedValueCents,
      decisionType: e.decisionType,
      targetRole: e.targetPurchasingRole,
      targetName: nameOf(e.targetMembership?.user),
      urgencyTier: e.urgencyTier,
      status: e.status,
      resolution: e.resolution,
      resolvedByLabel: e.resolvedByLabel,
      summary: e.suggestedMessage || e.situationText,
      orderTitle: e.order?.title ?? null,
      orderId: e.order?.id ?? null,
      currency: e.order?.currency ?? "EUR",
      createdAt: e.createdAt,
      resolvedAt: e.resolvedAt,
    }));

    return NextResponse.json({
      members,
      bands,
      autoApproveMaxCents,
      escalations: escs,
    });
  } catch (err) {
    if (err instanceof UnauthorizedError || err instanceof ForbiddenError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }
}
