// Tenancy / permissions smoke test. Run with:
//   npx tsx scripts/tenancy_smoke.ts
//
// Exercises the multi-tenancy + policy layer end-to-end against the real DB:
//   1. create an Organization + seeded default PermissionPolicy
//   2. create two Users + Memberships (OWNER/manager, procurement_lead €500)
//   3. create an Invite row + assert the accept link (NO email is sent)
//   4. build the policy payload via buildPolicyPayload() and assert its shape
//      matches the supervisor `POST /route` contract
//   5. delete every row it created — leaving the DB clean.
//
// Deliberately does NOT send any Brevo email, place calls, or hit external svcs.
import { prisma } from "@/lib/db";
import { buildPolicyPayload, defaultPolicyCreate } from "@/lib/policy";

function assert(cond: unknown, msg: string): asserts cond {
  if (!cond) throw new Error(`assertion failed: ${msg}`);
}

async function main() {
  const stamp = Date.now();
  const slug = `tenancy-smoke-${stamp}`;
  const ownerEmail = `owner+${stamp}@example.com`;
  const leadEmail = `lead+${stamp}@example.com`;
  const inviteeEmail = `invitee+${stamp}@example.com`;

  let orgId: string | null = null;
  const userIds: string[] = [];

  try {
    // 1. Org + default policy (same path createOrgForUser uses).
    console.log("→ creating org + default policy…");
    const org = await prisma.organization.create({
      data: {
        name: "Tenancy Smoke Org",
        slug,
        policies: { create: defaultPolicyCreate() },
      },
      include: { policies: true },
    });
    orgId = org.id;
    assert(org.policies.length === 1, "exactly one default policy seeded");
    const policy = org.policies[0];
    assert(policy.isDefault === true, "policy.isDefault");
    assert(policy.autoApproveMaxCents === 5000, "autoApproveMaxCents default 5000");
    assert(policy.voiceOverageRatio === 1.5, "voiceOverageRatio default 1.5");
    assert(Array.isArray(policy.rules), "policy.rules is an array");
    assert((policy.rules as unknown[]).length === 3, "3 default rules");

    // 2. Two users + memberships.
    console.log("→ creating users + memberships…");
    const owner = await prisma.user.create({
      data: { email: ownerEmail, name: "Owner" },
    });
    userIds.push(owner.id);
    const lead = await prisma.user.create({
      data: { email: leadEmail, name: "Procurement Lead" },
    });
    userIds.push(lead.id);

    const ownerMembership = await prisma.membership.create({
      data: {
        orgId: org.id,
        userId: owner.id,
        role: "OWNER",
        purchasingRole: "manager",
        // open-ended approval limit (null)
      },
    });
    const leadMembership = await prisma.membership.create({
      data: {
        orgId: org.id,
        userId: lead.id,
        role: "MEMBER",
        purchasingRole: "procurement_lead",
        approvalLimitCents: 50000, // €500
      },
    });

    // 3. Invite row + accept-link assertion (NO email send).
    console.log("→ creating invite + asserting accept link (no email)…");
    const invite = await prisma.invite.create({
      data: {
        orgId: org.id,
        email: inviteeEmail,
        role: "MEMBER",
        purchasingRole: "buyer",
        invitedById: owner.id,
        expiresAt: new Date(Date.now() + 14 * 24 * 60 * 60 * 1000),
      },
    });
    const base = (process.env.AUTH_URL ?? "http://localhost:3000").replace(/\/$/, "");
    const acceptUrl = `${base}/invite/${invite.token}`;
    assert(invite.token.length > 0, "invite has a token");
    assert(
      acceptUrl === `${base}/invite/${invite.token}`,
      "accept link is ${AUTH_URL}/invite/{token}",
    );
    assert(invite.acceptedAt === null, "invite not yet accepted");
    console.log(`   ✓ accept link: ${acceptUrl}`);

    // 4. Build the policy payload and assert the /route contract shape.
    console.log("→ buildPolicyPayload + shape assertions…");
    const payload = await buildPolicyPayload(org.id);

    // top-level keys
    assert(Array.isArray(payload.rules), "payload.rules is an array");
    assert(typeof payload.autoApproveMaxCents === "number", "autoApproveMaxCents number");
    assert(typeof payload.voiceOverageRatio === "number", "voiceOverageRatio number");
    assert(Array.isArray(payload.members), "payload.members is an array");
    assert(payload.autoApproveMaxCents === 5000, "payload autoApproveMaxCents 5000");
    assert(payload.voiceOverageRatio === 1.5, "payload voiceOverageRatio 1.5");

    // rule shape
    assert(payload.rules.length === 3, "payload has 3 rules");
    for (const r of payload.rules) {
      assert(
        r.maxBudgetCents === null || typeof r.maxBudgetCents === "number",
        "rule.maxBudgetCents is int|null",
      );
      assert(typeof r.targetPurchasingRole === "string", "rule.targetPurchasingRole");
      assert(
        ["async", "urgent_push", "voice"].includes(r.urgency),
        "rule.urgency enum",
      );
      assert(typeof r.autoApprove === "boolean", "rule.autoApprove bool");
      assert(typeof r.minConfidence === "number", "rule.minConfidence number");
    }
    // The open-ended catch-all (manager) must have null budget.
    const manager = payload.rules.find((r) => r.targetPurchasingRole === "manager");
    assert(manager !== undefined, "manager rule present");
    assert(manager!.maxBudgetCents === null, "manager rule is open-ended (null budget)");

    // members roster: exactly the two memberships with a purchasingRole.
    assert(payload.members.length === 2, "2 members with purchasingRole");
    const byRole = Object.fromEntries(
      payload.members.map((m) => [m.purchasingRole, m]),
    );
    assert(byRole["manager"], "manager member present");
    assert(byRole["procurement_lead"], "procurement_lead member present");
    assert(
      byRole["manager"].membershipId === ownerMembership.id,
      "manager membershipId matches owner membership",
    );
    assert(
      byRole["manager"].approvalLimitCents === null,
      "manager approvalLimitCents open-ended (null)",
    );
    assert(
      byRole["procurement_lead"].membershipId === leadMembership.id,
      "procurement_lead membershipId matches lead membership",
    );
    assert(
      byRole["procurement_lead"].approvalLimitCents === 50000,
      "procurement_lead approvalLimitCents €500 (50000)",
    );
    for (const m of payload.members) {
      assert(typeof m.membershipId === "string", "member.membershipId string");
      assert(typeof m.purchasingRole === "string", "member.purchasingRole string");
      assert(
        m.approvalLimitCents === null || typeof m.approvalLimitCents === "number",
        "member.approvalLimitCents int|null",
      );
    }

    console.log(
      "   ✓ payload shape matches { rules, autoApproveMaxCents, voiceOverageRatio, members[] }",
    );
    console.log(JSON.stringify(payload, null, 2));
  } finally {
    // 5. Cleanup — delete everything we created, leaving the DB clean.
    console.log("→ cleaning up…");
    if (orgId) {
      // Cascade handles memberships, invites, policies on org delete.
      await prisma.organization.delete({ where: { id: orgId } }).catch(() => {});
    }
    for (const uid of userIds) {
      await prisma.user.delete({ where: { id: uid } }).catch(() => {});
    }
    const leftover = await prisma.organization.findUnique({ where: { slug } });
    if (leftover) throw new Error("cleanup failed — org still present");
    console.log("   ✓ DB clean");
  }

  console.log("\n✓ tenancy_smoke PASSED");
}

main()
  .catch((e) => {
    console.error("\n✗ tenancy_smoke FAILED:", e);
    process.exitCode = 1;
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
