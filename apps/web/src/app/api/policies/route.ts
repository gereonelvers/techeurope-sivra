import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import {
  requireSession,
  activeOrg,
  assertOrgAccess,
  assertCanManage,
  UnauthorizedError,
  ForbiddenError,
} from "@/lib/org";
import {
  sanitizeRule,
  rulesToJson,
  defaultPolicyCreate,
  DEFAULT_AUTO_APPROVE_MAX_CENTS,
  DEFAULT_VOICE_OVERAGE_RATIO,
  type PolicyRule,
} from "@/lib/policy";

// Resolve the target org for a policy request. Accepts an explicit ?orgId= /
// body.orgId (membership-checked), else the user's active org.
async function resolveOrgId(explicit?: string | null): Promise<string> {
  if (explicit) {
    await assertOrgAccess(explicit);
    return explicit;
  }
  const session = await requireSession();
  const m = await activeOrg(session);
  if (!m) throw new ForbiddenError("No active organization");
  return m.orgId;
}

// GET /api/policies — the active org's current PermissionPolicy.
export async function GET(req: NextRequest) {
  try {
    const orgId = await resolveOrgId(req.nextUrl.searchParams.get("orgId"));
    await assertOrgAccess(orgId); // explicit org-scope guard

    let policy = await prisma.permissionPolicy.findFirst({
      where: { orgId },
      orderBy: [{ isDefault: "desc" }, { createdAt: "asc" }],
    });
    // Self-heal: if an org somehow has no policy, seed the default.
    if (!policy) {
      policy = await prisma.permissionPolicy.create({
        data: { orgId, ...defaultPolicyCreate() },
      });
    }
    return NextResponse.json({ policy });
  } catch (err) {
    if (err instanceof UnauthorizedError || err instanceof ForbiddenError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }
}

// PUT /api/policies — replace the active org's policy rules + global knobs.
// OWNER/ADMIN only.
export async function PUT(req: NextRequest) {
  try {
    const body = (await req.json().catch(() => ({}))) as {
      orgId?: string;
      rules?: unknown[];
      autoApproveMaxCents?: number;
      voiceOverageRatio?: number;
    };

    const orgId = await resolveOrgId(body.orgId ?? null);
    await assertCanManage(orgId); // membership + RBAC (OWNER/ADMIN)

    const rules: PolicyRule[] = Array.isArray(body.rules)
      ? body.rules.map(sanitizeRule)
      : [];

    const autoApproveMaxCents = Number.isFinite(Number(body.autoApproveMaxCents))
      ? Math.max(0, Math.round(Number(body.autoApproveMaxCents)))
      : DEFAULT_AUTO_APPROVE_MAX_CENTS;

    const voiceOverageRatio = Number.isFinite(Number(body.voiceOverageRatio))
      ? Math.max(1, Number(body.voiceOverageRatio))
      : DEFAULT_VOICE_OVERAGE_RATIO;

    const existing = await prisma.permissionPolicy.findFirst({
      where: { orgId },
      orderBy: [{ isDefault: "desc" }, { createdAt: "asc" }],
      select: { id: true },
    });

    const policy = existing
      ? await prisma.permissionPolicy.update({
          where: { id: existing.id },
          data: { rules: rulesToJson(rules), autoApproveMaxCents, voiceOverageRatio },
        })
      : await prisma.permissionPolicy.create({
          data: {
            orgId,
            name: "Default policy",
            isDefault: true,
            rules: rulesToJson(rules),
            autoApproveMaxCents,
            voiceOverageRatio,
          },
        });

    return NextResponse.json({ policy });
  } catch (err) {
    if (err instanceof UnauthorizedError || err instanceof ForbiddenError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }
}
