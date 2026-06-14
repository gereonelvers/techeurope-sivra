import { requireSession, activeOrg, canManageOrg } from "@/lib/org";
import { prisma } from "@/lib/db";
import { TeamManager } from "./TeamManager";

// Team page: list members (email, role, purchasingRole, approvalLimit), pending
// invites, and — for OWNER/ADMIN — invite/edit/remove controls. All reads are
// org-scoped to the active org. Mutations go through /api/members/* and
// /api/invites/* which re-check RBAC server-side.
export default async function TeamPage() {
  const session = await requireSession();
  const active = await activeOrg(session);
  if (!active) return null;

  const canManage = canManageOrg(active.role);

  const [members, invites] = await Promise.all([
    prisma.membership.findMany({
      where: { orgId: active.orgId },
      orderBy: { createdAt: "asc" },
      include: { user: { select: { email: true, name: true } } },
    }),
    prisma.invite.findMany({
      where: { orgId: active.orgId, acceptedAt: null },
      orderBy: { createdAt: "desc" },
    }),
  ]);

  const memberRows = members.map((m) => ({
    id: m.id,
    email: m.user.email,
    name: m.user.name,
    role: m.role,
    purchasingRole: m.purchasingRole,
    approvalLimitCents: m.approvalLimitCents,
    isSelf: m.userId === session.user.id,
  }));

  const inviteRows = invites.map((i) => ({
    id: i.id,
    email: i.email,
    role: i.role,
    purchasingRole: i.purchasingRole,
    expiresAt: i.expiresAt.toISOString(),
  }));

  return (
    <div>
      <header className="border-b border-ink/10 pb-6">
        <h1 className="text-3xl font-semibold">Team</h1>
        <p className="mt-2 text-sm text-ink/60">
          Members of {active.org.name}, their roles and approval limits.
          {!canManage ? " You have view-only access." : ""}
        </p>
      </header>

      <TeamManager
        members={memberRows}
        invites={inviteRows}
        canManage={canManage}
      />
    </div>
  );
}
