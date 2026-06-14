import { requireSession, activeOrg, canManageOrg } from "@/lib/org";
import { prisma } from "@/lib/db";
import {
  defaultPolicyCreate,
  DEFAULT_POLICY_RULES,
  DEFAULT_AUTO_APPROVE_MAX_CENTS,
  DEFAULT_VOICE_OVERAGE_RATIO,
  sanitizeRule,
  type PolicyRule,
} from "@/lib/policy";
import { PolicyEditor } from "./PolicyEditor";
import { RoutingMap } from "./RoutingMap";

// Policy editor page: the org's customizable escalation flow. Loads the current
// PermissionPolicy (org-scoped), self-heals a missing one, and hands it to the
// client editor. Edits PUT to /api/policies which re-checks OWNER/ADMIN RBAC.
export default async function PoliciesPage() {
  const session = await requireSession();
  const active = await activeOrg(session);
  if (!active) return null;

  const canManage = canManageOrg(active.role);

  let policy = await prisma.permissionPolicy.findFirst({
    where: { orgId: active.orgId },
    orderBy: [{ isDefault: "desc" }, { createdAt: "asc" }],
  });
  if (!policy) {
    policy = await prisma.permissionPolicy.create({
      data: { orgId: active.orgId, ...defaultPolicyCreate() },
    });
  }

  const rules: PolicyRule[] = Array.isArray(policy.rules)
    ? (policy.rules as unknown[]).map(sanitizeRule)
    : DEFAULT_POLICY_RULES;

  return (
    <div>
      <header className="border-b border-ink/10 pb-6">
        <h1 className="text-3xl font-semibold">Policies</h1>
        <p className="mt-2 max-w-prose text-sm leading-relaxed text-ink/60">
          The escalation flow for {active.org.name}. Ordered budget bands decide
          who signs off and how loudly. This is exactly what the routing brain
          consumes when it decides whom to ping.
          {!canManage ? " You have view-only access." : ""}
        </p>
      </header>

      {/* Live decision-routing map (team + paths + recent escalations). */}
      <RoutingMap />

      <div className="mt-10 border-t border-ink/10 pt-8">
        <h2 className="text-lg font-semibold">Budget bands</h2>
        <p className="mt-0.5 max-w-prose text-sm text-ink/55">
          The ordered rules the routing map above is built from — edit who signs
          off at each threshold.
        </p>
      </div>

      <PolicyEditor
        initialRules={rules}
        initialAutoApproveMaxCents={
          policy.autoApproveMaxCents ?? DEFAULT_AUTO_APPROVE_MAX_CENTS
        }
        initialVoiceOverageRatio={
          policy.voiceOverageRatio ?? DEFAULT_VOICE_OVERAGE_RATIO
        }
        canManage={canManage}
      />
    </div>
  );
}
