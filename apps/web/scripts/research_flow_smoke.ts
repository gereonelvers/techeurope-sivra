// Research → decision flow smoke test. Run with:
//   DISPATCH_DRY_RUN=1 npx tsx scripts/research_flow_smoke.ts
//
// Exercises POST /api/internal/orders/:id/research end-to-end against the real
// DB + the REAL Next routes + the REAL stateless supervisor /route:
//   0. spawn the supervisor (uvicorn) + the Next standalone server on free ports
//   1. seed org + default policy + a requester member WITH an approvalLimit
//   2. AUTO-BUY: an in-budget report where the requester is authorized →
//      order COMPLETED, receipt.autoBought, "purchased"+"completed" events,
//      NO escalation, NO human.
//   3. ESCALATE: a second order + an OVER-BUDGET report → exactly ONE escalation
//      created (routed via the supervisor /route), order ESCALATED, dispatch
//      attempted (dry-run, nothing actually sent).
//   4. delete every row created; verify the DB is clean.
//
// No SMS / calls / emails are sent (DISPATCH_DRY_RUN=1). Nothing is deployed.
import { spawn, type ChildProcess } from "child_process";
import { createServer } from "net";
import { readFileSync } from "fs";
import path from "path";

const REPO_ROOT = path.resolve(__dirname, "../../..");
const WEB_ROOT = path.resolve(__dirname, "..");
const VENV_UVICORN = path.join(REPO_ROOT, ".venv/bin/uvicorn");

function loadDotenv(file: string) {
  let raw: string;
  try {
    raw = readFileSync(file, "utf8");
  } catch {
    return;
  }
  for (const line of raw.split("\n")) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/i);
    if (!m) continue;
    const key = m[1];
    if (process.env[key] !== undefined) continue;
    let val = m[2].trim();
    if (
      (val.startsWith('"') && val.endsWith('"')) ||
      (val.startsWith("'") && val.endsWith("'"))
    ) {
      val = val.slice(1, -1);
    }
    process.env[key] = val;
  }
}
loadDotenv(path.join(WEB_ROOT, ".env"));

import { prisma } from "@/lib/db";

const INTERNAL_TOKEN = process.env.INTERNAL_API_TOKEN ?? "smoke-internal-token";

function assert(cond: unknown, msg: string): asserts cond {
  if (!cond) throw new Error(`assertion failed: ${msg}`);
}

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const srv = createServer();
    srv.unref();
    srv.on("error", reject);
    srv.listen(0, () => {
      const addr = srv.address();
      const port = typeof addr === "object" && addr ? addr.port : 0;
      srv.close(() => resolve(port));
    });
  });
}

async function waitForHttp(
  url: string,
  label: string,
  timeoutMs = 90000,
  headers: Record<string, string> = {},
) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(url, { headers, signal: AbortSignal.timeout(3000) });
      if (res.status > 0) return;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`${label} did not come up at ${url} within ${timeoutMs}ms`);
}

async function main() {
  const stamp = Date.now();
  const slug = `research-smoke-${stamp}`;

  let supervisor: ChildProcess | null = null;
  let web: ChildProcess | null = null;
  let orgId: string | null = null;
  const userIds: string[] = [];

  try {
    // ── 0. Spawn supervisor /route + the Next app server ──────────────────────
    const supervisorPort = await freePort();
    const webPort = await freePort();
    const supervisorUrl = `http://127.0.0.1:${supervisorPort}`;
    const webUrl = `http://127.0.0.1:${webPort}`;

    console.log(`→ starting supervisor (uvicorn) on :${supervisorPort}…`);
    supervisor = spawn(
      VENV_UVICORN,
      ["supervisor.app:app", "--host", "127.0.0.1", "--port", String(supervisorPort), "--log-level", "warning"],
      { cwd: REPO_ROOT, stdio: ["ignore", "inherit", "inherit"] },
    );
    await waitForHttp(`${supervisorUrl}/health`, "supervisor", 60000);
    console.log("   ✓ supervisor up");

    // Warm the supervisor /route once (first call cold-loads the router model and
    // can exceed the route's 15s budget). Best-effort — the route tolerates a
    // /route timeout by falling back to safe defaults.
    console.log("→ warming supervisor /route…");
    try {
      await fetch(`${supervisorUrl}/route`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          request: {
            request_id: `warm-${stamp}`,
            org_id: "warm",
            decision_type: "price_over_budget",
            situation_text: "warm-up",
            proposed_value: 100,
            budget_cap: 50,
            agent_confidence: 0.5,
            item: null,
          },
          policy: { rules: [], autoApproveMaxCents: 5000, voiceOverageRatio: 1.5, members: [] },
        }),
        signal: AbortSignal.timeout(60000),
      });
      console.log("   ✓ /route warm");
    } catch {
      console.log("   (warm-up timed out — continuing; route is best-effort)");
    }

    console.log(`→ starting Next app (standalone server) on :${webPort}…`);
    web = spawn(
      "node",
      [path.join(WEB_ROOT, ".next/standalone/server.js")],
      {
        cwd: WEB_ROOT,
        stdio: ["ignore", "inherit", "inherit"],
        env: {
          ...process.env,
          PORT: String(webPort),
          HOSTNAME: "127.0.0.1",
          SUPERVISOR_URL: supervisorUrl,
          DISPATCH_DRY_RUN: "1",
          AUTH_URL: webUrl,
          INTERNAL_API_TOKEN: INTERNAL_TOKEN,
          // no real orchestrator kick during the smoke
          ORCHESTRATOR_URL: "",
        },
      },
    );
    await waitForHttp(`${webUrl}/api/internal/ping`, "web", 90000, {
      "x-internal-token": INTERNAL_TOKEN,
    });
    console.log("   ✓ app up");

    const internalHeaders = {
      "Content-Type": "application/json",
      "x-internal-token": INTERNAL_TOKEN,
    };

    // ── 1. Org + default policy + a requester WITH an approval limit ──────────
    console.log("→ creating org + policy + requester (€500 approval limit)…");
    const { defaultPolicyCreate } = await import("@/lib/policy");
    const org = await prisma.organization.create({
      data: { name: "Research Smoke Org", slug, policies: { create: defaultPolicyCreate() } },
    });
    orgId = org.id;

    // A manager catch-all so escalations have somewhere to route.
    const managerUser = await prisma.user.create({
      data: { email: `mgr+${stamp}@example.com`, name: "Manager", phone: "+10000000010" },
    });
    userIds.push(managerUser.id);
    await prisma.membership.create({
      data: { orgId: org.id, userId: managerUser.id, role: "OWNER", purchasingRole: "manager" },
    });

    // The requester: a buyer with a €500 approval limit (authorizes the €92 buy).
    const requester = await prisma.user.create({
      data: { email: `buyer+${stamp}@example.com`, name: "Buyer", phone: "+10000000011" },
    });
    userIds.push(requester.id);
    await prisma.membership.create({
      data: {
        orgId: org.id,
        userId: requester.id,
        role: "MEMBER",
        purchasingRole: "buyer",
        approvalLimitCents: 50000, // €500
      },
    });

    // ── 2. AUTO-BUY: in-budget report, requester authorized ───────────────────
    console.log("→ AUTO-BUY case: order + in-budget report…");
    const autoOrder = await prisma.order.create({
      data: {
        orgId: org.id,
        requestedById: requester.id,
        title: "Cordless drill",
        description: "A basic cordless drill for the workshop",
        maxBudgetCents: 30000, // €300 cap
        intakeChannel: "CHAT",
        status: "SEARCHING",
        events: {
          create: { orgId: org.id, type: "created", actorType: "user", message: "Order created" },
        },
      },
    });

    const inBudgetReport = {
      round: 0,
      found: true,
      summary: "Cheapest matching cordless drill is a DeWalt at €92 — within the €300 cap.",
      bestCandidate: {
        title: "DeWalt DCD771",
        priceCents: 9200, // €92, well under the €500 requester limit
        site: "site-c",
        url: "/site-c/item/238",
        condition: "Good",
      },
      alternatives: [{ title: "Bosch GSR", priceCents: 11000, site: "site-a", url: "/site-a/item/91" }],
      inBudget: true,
      overBudgetByCents: 0,
      recommendation: "auto_buy",
      agentsRun: 6,
    };

    const autoRes = await fetch(`${webUrl}/api/internal/orders/${autoOrder.id}/research`, {
      method: "POST",
      headers: internalHeaders,
      body: JSON.stringify({ report: inBudgetReport }),
    });
    assert(autoRes.ok, `research(auto-buy) returned ${autoRes.status}`);
    const autoBody = await autoRes.json();
    console.log("   decision:", JSON.stringify(autoBody));
    assert(autoBody.decision === "auto_buy", `decision is auto_buy (got ${autoBody.decision})`);

    const completedOrder = await prisma.order.findUnique({ where: { id: autoOrder.id } });
    assert(completedOrder!.status === "COMPLETED", "auto-buy order is COMPLETED");
    assert(completedOrder!.completedAt != null, "completedAt set");
    assert(completedOrder!.resultTitle === "DeWalt DCD771", "resultTitle from bestCandidate");
    assert(completedOrder!.resultPriceCents === 9200, "resultPriceCents from bestCandidate");
    const receipt = (completedOrder!.receipt ?? {}) as { autoBought?: boolean; candidate?: unknown };
    assert(receipt.autoBought === true, "receipt.autoBought is true");
    assert(receipt.candidate != null, "receipt carries the candidate");
    const storedReport = (completedOrder!.report ?? {}) as { found?: boolean; inBudget?: boolean };
    assert(storedReport.found === true && storedReport.inBudget === true, "report stored on order");

    const autoEvents = await prisma.orderEvent.findMany({
      where: { orderId: autoOrder.id },
      orderBy: { createdAt: "asc" },
    });
    const autoTypes = autoEvents.map((e) => e.type);
    assert(autoTypes.includes("research_complete"), "research_complete event present");
    assert(autoTypes.includes("purchased"), "purchased event present");
    assert(autoTypes.includes("completed"), "completed event present");
    const researchEvent = autoEvents.find((e) => e.type === "research_complete");
    assert(researchEvent!.actorType === "supervisor", "research_complete actorType is supervisor");

    const autoEscalations = await prisma.escalation.count({ where: { orderId: autoOrder.id } });
    assert(autoEscalations === 0, `NO escalation created for auto-buy (got ${autoEscalations})`);
    console.log("   ✓ AUTO-BUY: COMPLETED, receipt.autoBought, no escalation, no human");

    // ── 3. ESCALATE: over-budget report → exactly ONE escalation ──────────────
    console.log("→ ESCALATE case: order + over-budget report…");
    const escOrder = await prisma.order.create({
      data: {
        orgId: org.id,
        requestedById: requester.id,
        title: "Standing desk",
        description: "Height-adjustable standing desk",
        maxBudgetCents: 30000, // €300 cap
        intakeChannel: "CHAT",
        status: "SEARCHING",
        events: {
          create: { orgId: org.id, type: "created", actorType: "user", message: "Order created" },
        },
      },
    });

    const overBudgetReport = {
      round: 0,
      found: true,
      summary: "Best matching desk is €450 on BidBay — €150 over the €300 cap.",
      bestCandidate: {
        title: "FlexiSpot E7",
        priceCents: 45000, // €450, over the €300 cap
        site: "site-b",
        url: "/site-b/item/512",
        condition: "New",
      },
      alternatives: [{ title: "IKEA Bekant", priceCents: 38000, site: "site-a" }],
      inBudget: false,
      overBudgetByCents: 15000,
      recommendation: "escalate_over_budget",
      agentsRun: 6,
    };

    const escRes = await fetch(`${webUrl}/api/internal/orders/${escOrder.id}/research`, {
      method: "POST",
      headers: internalHeaders,
      body: JSON.stringify({ report: overBudgetReport }),
    });
    assert(escRes.ok, `research(escalate) returned ${escRes.status}`);
    const escBody = await escRes.json();
    console.log("   decision:", JSON.stringify(escBody));
    assert(escBody.decision === "escalate", `decision is escalate (got ${escBody.decision})`);

    const escalatedOrder = await prisma.order.findUnique({ where: { id: escOrder.id } });
    assert(escalatedOrder!.status === "ESCALATED", "over-budget order is ESCALATED");

    const escalations = await prisma.escalation.findMany({ where: { orderId: escOrder.id } });
    assert(escalations.length === 1, `EXACTLY ONE escalation created (got ${escalations.length})`);
    const esc = escalations[0];
    assert(esc.status === "PENDING", "escalation starts PENDING");
    assert(esc.code.length >= 24, "escalation has an unguessable code");
    assert(esc.proposedValueCents === 45000, "proposedValueCents = bestCandidate price");
    assert(esc.budgetCapCents === 30000, "budgetCapCents = order cap");
    assert(esc.decisionType === "price_over_budget", "decisionType is price_over_budget");
    // The report is carried on the escalation (guardrail.report).
    const guardrail = (esc.guardrail ?? {}) as { report?: { found?: boolean }; researchRound?: number };
    assert(guardrail.report?.found === true, "escalation carries the report");
    assert(guardrail.researchRound === 0, "escalation tagged with researchRound 0");
    // The supervisor /route was invoked. It either returned a routing decision
    // (routerVersion/routing stored) or timed out, in which case the route falls
    // back to safe delegating defaults — both are valid; the escalation exists
    // either way. Assert the fallback contract holds.
    assert(esc.shouldDelegate === true, "escalation delegates to a human");
    if (esc.routerVersion != null || esc.routing != null) {
      console.log("   (supervisor /route returned a routing decision)");
    } else {
      console.log("   (supervisor /route timed out — safe delegating defaults applied)");
    }

    const escEvents = await prisma.orderEvent.findMany({
      where: { orderId: escOrder.id },
      orderBy: { createdAt: "asc" },
    });
    const escTypes = escEvents.map((e) => e.type);
    assert(escTypes.includes("research_complete"), "research_complete event present");
    assert(escTypes.includes("escalated"), "escalated event present");
    assert(escTypes.includes("notified"), "notified event present (dispatch attempted)");
    const escEvent = escEvents.find((e) => e.type === "escalated");
    assert(escEvent!.actorType === "supervisor", "escalated event spoken in supervisor voice");

    // Dispatch ran in dry-run.
    const notified = escEvents.find((e) => e.type === "notified");
    const dispatchData = (notified?.data ?? {}) as { dispatch?: Array<{ dryRun?: boolean }> };
    assert(
      Array.isArray(dispatchData.dispatch) && dispatchData.dispatch.every((d) => d.dryRun === true),
      "dispatch ran in DRY-RUN (nothing actually sent)",
    );

    const noPurchase = escEvents.find((e) => e.type === "purchased");
    assert(!noPurchase, "no auto-purchase happened for the over-budget order");
    console.log("   ✓ ESCALATE: ONE escalation, order ESCALATED, dispatch dry-run, no auto-buy");

    // ── 3b. Idempotency: re-POST the same over-budget report → no 2nd escalation
    console.log("→ idempotency: re-POST the same report…");
    const dupRes = await fetch(`${webUrl}/api/internal/orders/${escOrder.id}/research`, {
      method: "POST",
      headers: internalHeaders,
      body: JSON.stringify({ report: overBudgetReport }),
    });
    assert(dupRes.ok, `duplicate research returned ${dupRes.status}`);
    const dupBody = await dupRes.json();
    assert(dupBody.alreadyProcessed === true, "duplicate report is idempotent");
    const escCountAfter = await prisma.escalation.count({ where: { orderId: escOrder.id } });
    assert(escCountAfter === 1, `still exactly ONE escalation after re-POST (got ${escCountAfter})`);
    console.log("   ✓ idempotent — still one escalation");

    console.log("\n✓ research_flow_smoke PASSED");
  } finally {
    // ── 4. Cleanup ────────────────────────────────────────────────────────────
    console.log("→ cleaning up…");
    if (orgId) {
      await prisma.organization.delete({ where: { id: orgId } }).catch(() => {});
    }
    for (const uid of userIds) {
      await prisma.user.delete({ where: { id: uid } }).catch(() => {});
    }
    const leftover = await prisma.organization.findUnique({ where: { slug } });
    if (leftover) throw new Error("cleanup failed — org still present");
    console.log("   ✓ DB clean");

    if (web && !web.killed) web.kill("SIGKILL");
    if (supervisor && !supervisor.killed) supervisor.kill("SIGKILL");
  }
}

main()
  .catch((e) => {
    console.error("\n✗ research_flow_smoke FAILED:", e);
    process.exitCode = 1;
  })
  .finally(async () => {
    await prisma.$disconnect();
    setTimeout(() => process.exit(process.exitCode ?? 0), 500);
  });
