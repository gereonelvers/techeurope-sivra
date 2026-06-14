// Live end-to-end test of the research → supervisor → decision flow against the
// DEPLOYED system (sivra.io app + the deployed Modal fleet). Seeds an authorized
// requester + an in-budget order, triggers the live fleet, polls until terminal.
import { prisma } from "../src/lib/db";

const MODAL = "https://gereonelvers99--sivra-fleet-launch.modal.run";
const ts = Date.now();

async function main() {
  const org = await prisma.organization.create({ data: { name: "E2E Test Co", slug: `e2e-${ts}` } });
  await prisma.permissionPolicy.create({
    data: {
      orgId: org.id,
      rules: [{ maxBudgetCents: null, targetPurchasingRole: "manager", urgency: "voice", autoApprove: false, minConfidence: null }],
      autoApproveMaxCents: 5000, voiceOverageRatio: 1.5,
    },
  });
  const user = await prisma.user.create({ data: { email: `e2e-${ts}@test.local`, name: "E2E Requester" } }); // no phone → no dispatch spam even if it escalates
  await prisma.membership.create({ data: { orgId: org.id, userId: user.id, role: "OWNER", purchasingRole: "manager", approvalLimitCents: 100000 } });
  const order = await prisma.order.create({
    data: { orgId: org.id, requestedById: user.id, title: "OnePlus phone", maxBudgetCents: 20000, currency: "EUR", status: "SEARCHING", intakeChannel: "CHAT" },
  });
  console.log(`SEEDED  org=${org.id}  order=${order.id}  (budget €200, requester authorized to €1000)`);

  const r = await fetch(MODAL, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ orgId: org.id, orderId: order.id, goal: "OnePlus phone under 200 euros", budgetCents: 20000, n: 3 }),
  });
  console.log(`LAUNCH  -> ${r.status}  ${(await r.text()).slice(0, 160)}`);

  let last = "";
  for (let i = 0; i < 16; i++) {
    await new Promise((s) => setTimeout(s, 15000));
    const o = await prisma.order.findUnique({ where: { id: order.id } });
    const events = await prisma.orderEvent.findMany({ where: { orderId: order.id }, orderBy: { createdAt: "asc" } });
    const line = `[${(i + 1) * 15}s] status=${o?.status} report=${o?.report ? "✓" : "—"} events=[${events.map((e) => e.type).join(", ")}]`;
    if (line !== last) console.log(line); last = line;
    if (o?.status === "COMPLETED" || o?.status === "ESCALATED" || o?.status === "FAILED") {
      console.log("\n=== SUPERVISOR NARRATION (audit trail) ===");
      events.filter((e) => e.actorType === "supervisor").forEach((e) => console.log("  •", e.message));
      console.log("\n=== FINAL REPORT ===");
      console.log(JSON.stringify(o?.report, null, 1)?.slice(0, 900));
      console.log("\n=== OUTCOME ===", o?.status, "| receipt:", JSON.stringify(o?.receipt)?.slice(0, 300));
      break;
    }
  }
  console.log(`\n(test order left in DB for inspection: order=${order.id})`);
}
main().then(() => process.exit(0)).catch((e) => { console.error(e); process.exit(1); });
