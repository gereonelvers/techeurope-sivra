import { cookies } from "next/headers";
import type { Session } from "next-auth";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/db";

/** Cookie that persists the user's active org across requests (org switcher). */
export const ORG_COOKIE = "sivra_org";

// ─────────────────────────────────────────────────────────────────────────────
// Org-scoping helpers. THE rule (ARCHITECTURE.md): every product query is
// scoped by orgId derived from the session — no exceptions. Feature agents:
// 1. const session = await requireSession()           // 401 if not signed in
// 2. const membership = await activeMembership(session) // user's membership
// 3. await assertOrgAccess(orgId)                      // before any orgId query
// ─────────────────────────────────────────────────────────────────────────────

export class UnauthorizedError extends Error {
  status = 401 as const;
  constructor(message = "Not authenticated") {
    super(message);
    this.name = "UnauthorizedError";
  }
}

export class ForbiddenError extends Error {
  status = 403 as const;
  constructor(message = "No access to this organization") {
    super(message);
    this.name = "ForbiddenError";
  }
}

/** Returns the active session or throws UnauthorizedError (handlers → 401). */
export async function requireSession(): Promise<Session> {
  const session = await auth();
  if (!session?.user?.id) throw new UnauthorizedError();
  return session;
}

export interface MembershipWithOrg {
  id: string;
  orgId: string;
  userId: string;
  role: string;
  purchasingRole: string | null;
  approvalLimitCents: number | null;
  org: { id: string; name: string; slug: string };
}

/**
 * The signed-in user's "active" membership. Until an org switcher lands
 * (W-auth), this is simply their first/oldest membership. Returns null if the
 * user belongs to no org yet (the dashboard then offers "Create organization").
 */
export async function activeMembership(
  session: Session,
): Promise<MembershipWithOrg | null> {
  const userId = session.user?.id;
  if (!userId) return null;
  const membership = await prisma.membership.findFirst({
    where: { userId },
    orderBy: { createdAt: "asc" },
    include: { org: { select: { id: true, name: true, slug: true } } },
  });
  return membership as MembershipWithOrg | null;
}

/**
 * The signed-in user's active membership, honoring the `sivra_org` cookie. If
 * the cookie names an org the user actually belongs to, that membership wins;
 * otherwise we fall back to their first/oldest membership (or null if none).
 *
 * This is the org-switcher-aware replacement for activeMembership(): every
 * org-scoped page derives its orgId from here.
 */
export async function activeOrg(
  session: Session,
): Promise<MembershipWithOrg | null> {
  const userId = session.user?.id;
  if (!userId) return null;

  const preferredOrgId = cookies().get(ORG_COOKIE)?.value;
  if (preferredOrgId) {
    const preferred = await prisma.membership.findUnique({
      where: { orgId_userId: { orgId: preferredOrgId, userId } },
      include: { org: { select: { id: true, name: true, slug: true } } },
    });
    if (preferred) return preferred as MembershipWithOrg;
  }

  // Fallback: first membership (mirrors activeMembership).
  return activeMembership(session);
}

/** All orgs the signed-in user is a member of. */
export async function listMemberships(
  session: Session,
): Promise<MembershipWithOrg[]> {
  const userId = session.user?.id;
  if (!userId) return [];
  const memberships = await prisma.membership.findMany({
    where: { userId },
    orderBy: { createdAt: "asc" },
    include: { org: { select: { id: true, name: true, slug: true } } },
  });
  return memberships as MembershipWithOrg[];
}

/**
 * Assert the current session's user is a member of `orgId`. Call this BEFORE
 * any query/mutation touching that org's data. Returns the membership so the
 * caller can branch on role / approvalLimit without a second round-trip.
 */
export async function assertOrgAccess(orgId: string): Promise<MembershipWithOrg> {
  const session = await requireSession();
  const userId = session.user!.id!;
  const membership = await prisma.membership.findUnique({
    where: { orgId_userId: { orgId, userId } },
    include: { org: { select: { id: true, name: true, slug: true } } },
  });
  if (!membership) throw new ForbiddenError();
  return membership as MembershipWithOrg;
}

/** Org roles allowed to manage team + policies. */
export function canManageOrg(role: string): boolean {
  return role === "OWNER" || role === "ADMIN";
}

/**
 * Assert the current user may manage `orgId` (team / policies / settings).
 * Combines org membership + RBAC (OWNER or ADMIN). Returns the membership.
 */
export async function assertCanManage(orgId: string): Promise<MembershipWithOrg> {
  const membership = await assertOrgAccess(orgId);
  if (!canManageOrg(membership.role)) {
    throw new ForbiddenError("Requires OWNER or ADMIN");
  }
  return membership;
}

/**
 * Create an Organization owned by `userId`: org + OWNER Membership
 * (purchasingRole=manager) + a seeded default PermissionPolicy, all in one
 * transaction so the org is immediately usable by the fleet. Returns the org.
 */
export async function createOrgForUser(userId: string, name: string) {
  // Imported lazily to avoid a lib/lib import cycle at module-eval time.
  const { uniqueSlug, defaultPolicyCreate } = await import("@/lib/policy");
  const slug = await uniqueSlug(name);
  return prisma.organization.create({
    data: {
      name,
      slug,
      memberships: {
        create: { userId, role: "OWNER", purchasingRole: "manager" },
      },
      policies: { create: defaultPolicyCreate() },
    },
    select: { id: true, name: true, slug: true },
  });
}
