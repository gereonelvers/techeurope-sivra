import { Prisma } from "@prisma/client";
import { prisma } from "@/lib/db";

// ─────────────────────────────────────────────────────────────────────────────
// Permission / escalation policy. This is the per-org "customizable escalation
// flow": an ordered list of budget-band rules plus a couple of global knobs.
// The JSON shape here is EXACTLY what the supervisor `POST /route` consumes as
// its `policy` field (see ARCHITECTURE.md "Supervisor (stateless) contract"):
//   { rules, autoApproveMaxCents, voiceOverageRatio,
//     members: [{ purchasingRole, approvalLimitCents, membershipId }] }
// Money is integer cents everywhere.
// ─────────────────────────────────────────────────────────────────────────────

/** The three purchasing roles the router taxonomy understands. */
export const PURCHASING_ROLES = ["buyer", "procurement_lead", "manager"] as const;
export type PurchasingRole = (typeof PURCHASING_ROLES)[number];

/** Urgency tiers a rule may request. */
export const URGENCY_TIERS = ["async", "urgent_push", "voice"] as const;
export type Urgency = (typeof URGENCY_TIERS)[number];

/**
 * One ordered escalation rule. `maxBudgetCents=null` means "no upper bound"
 * (open-ended — typically the manager catch-all). Rules are evaluated in order;
 * the first whose budget band covers the proposed value wins.
 */
export interface PolicyRule {
  /** Inclusive upper bound of this band in cents; null = open-ended. */
  maxBudgetCents: number | null;
  targetPurchasingRole: PurchasingRole;
  urgency: Urgency;
  /** If true and confidence ≥ minConfidence, auto-approve without a human. */
  autoApprove: boolean;
  /** Minimum agent confidence [0..1] required to act on this rule. */
  minConfidence: number;
}

/** A member row as the supervisor's router roster expects it. */
export interface PolicyMember {
  purchasingRole: PurchasingRole | string;
  approvalLimitCents: number | null;
  membershipId: string;
}

/** The full policy payload sent to supervisor `POST /route`. */
export interface PolicyPayload {
  rules: PolicyRule[];
  autoApproveMaxCents: number;
  voiceOverageRatio: number;
  members: PolicyMember[];
}

/** Default global knobs seeded on org creation. */
export const DEFAULT_AUTO_APPROVE_MAX_CENTS = 5000; // €50
export const DEFAULT_VOICE_OVERAGE_RATIO = 1.5;

/**
 * Default ordered escalation rules seeded with each new org:
 *   buyer ≤ €150 · procurement_lead ≤ €500 · manager open-ended.
 * Shape matches the PermissionPolicy.rules comment in schema.prisma.
 */
export const DEFAULT_POLICY_RULES: PolicyRule[] = [
  {
    maxBudgetCents: 15000, // €150
    targetPurchasingRole: "buyer",
    urgency: "async",
    autoApprove: true,
    minConfidence: 0.7,
  },
  {
    maxBudgetCents: 50000, // €500
    targetPurchasingRole: "procurement_lead",
    urgency: "urgent_push",
    autoApprove: false,
    minConfidence: 0.6,
  },
  {
    maxBudgetCents: null, // open-ended
    targetPurchasingRole: "manager",
    urgency: "voice",
    autoApprove: false,
    minConfidence: 0.5,
  },
];

/** Cast typed rules to the Prisma JSON input type for create/update. */
export function rulesToJson(rules: PolicyRule[]): Prisma.InputJsonValue {
  return rules as unknown as Prisma.InputJsonValue;
}

/** Prisma `create` block for an org's default policy. */
export function defaultPolicyCreate() {
  return {
    name: "Default policy",
    isDefault: true,
    rules: rulesToJson(DEFAULT_POLICY_RULES),
    autoApproveMaxCents: DEFAULT_AUTO_APPROVE_MAX_CENTS,
    voiceOverageRatio: DEFAULT_VOICE_OVERAGE_RATIO,
  };
}

/** Coerce arbitrary JSON into a clean, validated PolicyRule. */
export function sanitizeRule(raw: unknown): PolicyRule {
  const r = (raw ?? {}) as Record<string, unknown>;

  const maxBudgetCents =
    r.maxBudgetCents === null || r.maxBudgetCents === undefined
      ? null
      : Math.max(0, Math.round(Number(r.maxBudgetCents)));

  const role = String(r.targetPurchasingRole ?? "buyer");
  const targetPurchasingRole = (PURCHASING_ROLES as readonly string[]).includes(role)
    ? (role as PurchasingRole)
    : "buyer";

  const urg = String(r.urgency ?? "async");
  const urgency = (URGENCY_TIERS as readonly string[]).includes(urg)
    ? (urg as Urgency)
    : "async";

  const minConfidenceRaw = Number(r.minConfidence ?? 0.5);
  const minConfidence = Number.isFinite(minConfidenceRaw)
    ? Math.min(1, Math.max(0, minConfidenceRaw))
    : 0.5;

  return {
    maxBudgetCents: Number.isFinite(maxBudgetCents as number) ? maxBudgetCents : null,
    targetPurchasingRole,
    urgency,
    autoApprove: Boolean(r.autoApprove),
    minConfidence,
  };
}

/**
 * Assemble the policy payload the supervisor `/route` brain consumes, from the
 * org's PermissionPolicy + its memberships. The Orders/escalation agent calls
 * this when escalating an order so the router gets both the rules and the live
 * member roster (who can approve up to what).
 *
 * Org-scoping note: this is a pure read keyed by `orgId`. Its callers must have
 * already authorized access to that org — browser routes via assertOrgAccess(),
 * internal routes (the escalation path the orchestrator hits) via assertInternal()
 * + a trusted orgId in the request body. It does NOT do session auth itself so
 * it works from both contexts (and from the smoke test / cron).
 */
export async function buildPolicyPayload(orgId: string): Promise<PolicyPayload> {
  const policy = await prisma.permissionPolicy.findFirst({
    where: { orgId },
    orderBy: [{ isDefault: "desc" }, { createdAt: "asc" }],
  });

  const memberships = await prisma.membership.findMany({
    where: { orgId, purchasingRole: { not: null } },
    select: { id: true, purchasingRole: true, approvalLimitCents: true },
    orderBy: { createdAt: "asc" },
  });

  const rules: PolicyRule[] = Array.isArray(policy?.rules)
    ? (policy!.rules as unknown[]).map(sanitizeRule)
    : DEFAULT_POLICY_RULES;

  const members: PolicyMember[] = memberships.map((m) => ({
    purchasingRole: m.purchasingRole as string,
    approvalLimitCents: m.approvalLimitCents ?? null,
    membershipId: m.id,
  }));

  return {
    rules,
    autoApproveMaxCents: policy?.autoApproveMaxCents ?? DEFAULT_AUTO_APPROVE_MAX_CENTS,
    voiceOverageRatio: policy?.voiceOverageRatio ?? DEFAULT_VOICE_OVERAGE_RATIO,
    members,
  };
}

/** URL-safe slug from an org name; unique-ified by callers against the DB. */
export function slugify(name: string): string {
  const base = name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
  return base || "org";
}

/** Find a free slug derived from `name` (appends -1, -2, … on collision). */
export async function uniqueSlug(name: string): Promise<string> {
  const base = slugify(name);
  for (let i = 0; ; i++) {
    const candidate = i === 0 ? base : `${base}-${i}`;
    const taken = await prisma.organization.findUnique({
      where: { slug: candidate },
      select: { id: true },
    });
    if (!taken) return candidate;
  }
}
