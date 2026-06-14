// Order intake + escalation + resolution smoke test. Run with:
//   DISPATCH_DRY_RUN=1 npx tsx scripts/order_flow_smoke.ts
//
// Exercises the product spine end-to-end against the real DB + the REAL routes:
//   0. spawn the stateless supervisor `POST /route` locally (uvicorn from the
//      repo .venv on a free port) and the Next.js app server (next start on a
//      free port); point SUPERVISOR_URL at the local supervisor.
//   1. create org + default policy + member (procurement_lead, €500)
//   2. create an Order (DRAFT)
//   3. POST /api/internal/escalations with an over-budget proposal → it must
//      route via the supervisor, resolve a target member, ESCALATE the order,
//      and ATTEMPT dispatch (dry-run logged, never actually sent)
//   4. poll GET /api/internal/escalations/:requestId/resolution → 404 (pending)
//   5. POST /api/voice/resolve approve + good → escalation RESOLVED, reward +1,
//      order APPROVED, audit events present
//   6. GET …/resolution → 200 HumanResolution
//   7. delete every row created; verify the DB is clean
//
// No SMS / calls / emails are sent (DISPATCH_DRY_RUN=1). Nothing is deployed.
import { spawn, type ChildProcess } from "child_process";
import { createServer } from "net";
import { readFileSync } from "fs";
import path from "path";

const REPO_ROOT = path.resolve(__dirname, "../../..");
const WEB_ROOT = path.resolve(__dirname, "..");
const VENV_UVICORN = path.join(REPO_ROOT, ".venv/bin/uvicorn");

// Load apps/web/.env into process.env (so INTERNAL_API_TOKEN / DATABASE_URL
// match what the spawned standalone server uses). Existing env wins — this is
// a minimal dotenv that never clobbers a value already set (e.g. DISPATCH_DRY_RUN).
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

// Prisma resolves env("DATABASE_URL") lazily at connection time, so loading
// .env above (even though imports hoist) is enough for the client to connect.
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
  timeoutMs = 60000,
  headers: Record<string, string> = {},
) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(url, { headers, signal: AbortSignal.timeout(3000) });
      // Any HTTP response means the server is listening (401/404/405 included).
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
  const slug = `order-smoke-${stamp}`;
  const requestId = `req-smoke-${stamp}`;

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

    // The app is built with output:"standalone", so we run the self-contained
    // server bundle (next start is a no-op there). It reads PORT/HOSTNAME from env.
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
          // ensure no orchestrator kick is attempted
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

    // ── 1. Org + default policy + members ─────────────────────────────────────
    console.log("→ creating org + policy + members…");
    const { defaultPolicyCreate } = await import("@/lib/policy");
    const org = await prisma.organization.create({
      data: { name: "Order Smoke Org", slug, policies: { create: defaultPolicyCreate() } },
    });
    orgId = org.id;

    const ownerUser = await prisma.user.create({
      data: { email: `owner+${stamp}@example.com`, name: "Owner", phone: "+10000000000" },
    });
    userIds.push(ownerUser.id);
    await prisma.membership.create({
      data: { orgId: org.id, userId: ownerUser.id, role: "OWNER", purchasingRole: "manager" },
    });

    const leadUser = await prisma.user.create({
      data: { email: `lead+${stamp}@example.com`, name: "Procurement Lead", phone: "+10000000001" },
    });
    userIds.push(leadUser.id);
    const leadMembership = await prisma.membership.create({
      data: {
        orgId: org.id,
        userId: leadUser.id,
        role: "MEMBER",
        purchasingRole: "procurement_lead",
        approvalLimitCents: 50000, // €500
      },
    });

    // ── 2. Order (DRAFT) ──────────────────────────────────────────────────────
    console.log("→ creating order…");
    const order = await prisma.order.create({
      data: {
        orgId: org.id,
        requestedById: ownerUser.id,
        title: "Standing desk",
        description: "Height-adjustable standing desk for the new hire",
        maxBudgetCents: 30000, // €300
        intakeChannel: "CHAT",
        status: "SEARCHING",
        events: {
          create: { orgId: org.id, type: "created", actorType: "user", message: "Order created" },
        },
      },
    });

    // ── 3. POST /api/internal/escalations (over-budget → delegate) ────────────
    // proposed €450 (45000c) over a €300 cap; amount ≤ €500 band ⇒ procurement_lead.
    console.log("→ POST /api/internal/escalations (over-budget)…");
    const escRes = await fetch(`${webUrl}/api/internal/escalations`, {
      method: "POST",
      headers: internalHeaders,
      body: JSON.stringify({
        requestId,
        orgId: org.id,
        orderId: order.id,
        decisionType: "price_over_budget",
        situationText: "Best desk found is €450, which is over the €300 budget cap.",
        proposedValueCents: 45000,
        budgetCapCents: 30000,
        agentConfidence: 0.8,
        item: { title: "Standing desk", listed_price: 450.0, currency: "EUR" },
      }),
    });
    assert(escRes.ok, `escalations returned ${escRes.status}`);
    const routing = await escRes.json();
    console.log("   routing decision:", JSON.stringify(routing));
    assert(routing.request_id === requestId, "routing.request_id echoes requestId");
    assert(routing.should_delegate === true, "should_delegate is true (over budget)");
    assert(
      routing.target_purchasing_role === "procurement_lead",
      `target role is procurement_lead (got ${routing.target_purchasing_role})`,
    );
    assert(
      routing.target_membership_id === leadMembership.id,
      "target_membership_id resolved to the procurement_lead member",
    );
    assert(typeof routing.urgency_tier === "string", "urgency_tier present");
    assert(typeof routing.suggested_message === "string", "suggested_message present");

    // Persisted escalation got the routing decision + a code; order escalated.
    const persisted = await prisma.escalation.findUnique({ where: { requestId } });
    assert(persisted, "escalation persisted");
    assert(persisted!.status === "PENDING", "escalation starts PENDING");
    assert(persisted!.code.length >= 24, "escalation has an unguessable code (>=24 chars)");
    assert(persisted!.targetMembershipId === leadMembership.id, "stored target membership");
    assert(persisted!.routerVersion != null, "router version stored");
    assert(persisted!.routing != null, "full routing json stored");

    const escalatedOrder = await prisma.order.findUnique({ where: { id: order.id } });
    assert(escalatedOrder!.status === "ESCALATED", "order flipped to ESCALATED");

    const eventsAfterEsc = await prisma.orderEvent.findMany({
      where: { orderId: order.id },
      orderBy: { createdAt: "asc" },
    });
    const types = eventsAfterEsc.map((e) => e.type);
    assert(types.includes("escalated"), "escalated audit event present");
    assert(types.includes("notified"), "notified audit event present (dispatch attempted)");

    // Dispatch was attempted in dry-run: the notified event records the channel.
    const notified = eventsAfterEsc.find((e) => e.type === "notified");
    const dispatchData = (notified?.data ?? {}) as { dispatch?: Array<{ dryRun?: boolean }> };
    assert(
      Array.isArray(dispatchData.dispatch) && dispatchData.dispatch.length > 0,
      "dispatch attempt recorded on the notified event",
    );
    assert(
      dispatchData.dispatch.every((d) => d.dryRun === true),
      "dispatch ran in DRY-RUN (nothing actually sent)",
    );
    console.log("   ✓ escalation routed, order ESCALATED, dispatch attempted (dry-run)");

    // ── 4. Poll resolution → 404 while PENDING ────────────────────────────────
    console.log("→ GET …/resolution (expect 404 pending)…");
    const pendingRes = await fetch(
      `${webUrl}/api/internal/escalations/${requestId}/resolution`,
      { headers: { "x-internal-token": INTERNAL_TOKEN } },
    );
    assert(pendingRes.status === 404, `resolution is 404 while pending (got ${pendingRes.status})`);
    console.log("   ✓ 404 while pending");

    // ── 5. POST /api/voice/resolve approve + good ─────────────────────────────
    console.log("→ POST /api/voice/resolve (approve + good)…");
    const resolveRes = await fetch(`${webUrl}/api/voice/resolve`, {
      method: "POST",
      headers: internalHeaders,
      body: JSON.stringify({
        request_id: requestId,
        resolution: "approve",
        value: 450.0,
        rating: "good",
        resolvedByLabel: "voice (smoke)",
      }),
    });
    assert(resolveRes.ok, `voice/resolve returned ${resolveRes.status}`);
    const resolveBody = await resolveRes.json();
    console.log("   resolve result:", JSON.stringify(resolveBody));

    const resolved = await prisma.escalation.findUnique({ where: { requestId } });
    assert(resolved!.status === "RESOLVED", "escalation RESOLVED");
    assert(resolved!.resolution === "approve", "resolution recorded as approve");
    assert(resolved!.rating === "good", "rating recorded as good");
    assert(resolved!.rewardScalar === 1, `rewardScalar is +1 for good (got ${resolved!.rewardScalar})`);
    assert(resolved!.latencyMs != null && resolved!.latencyMs >= 0, "latencyMs computed");
    assert(resolved!.resolvedAt != null, "resolvedAt set");

    // approve → the order is completed with a receipt (RESEARCH-FLOW.md §4).
    const approvedOrder = await prisma.order.findUnique({ where: { id: order.id } });
    assert(approvedOrder!.status === "COMPLETED", "order completed on approval");

    const finalEvents = await prisma.orderEvent.findMany({
      where: { orderId: order.id },
      orderBy: { createdAt: "asc" },
    });
    assert(finalEvents.some((e) => e.type === "approved"), "approved audit event present");
    assert(finalEvents.some((e) => e.type === "completed"), "completed audit event present");
    console.log("   ✓ RESOLVED, reward +1, order COMPLETED, audit events present");

    // ── 6. GET …/resolution → 200 HumanResolution ─────────────────────────────
    console.log("→ GET …/resolution (expect 200)…");
    const okRes = await fetch(
      `${webUrl}/api/internal/escalations/${requestId}/resolution`,
      { headers: { "x-internal-token": INTERNAL_TOKEN } },
    );
    assert(okRes.status === 200, `resolution is 200 once resolved (got ${okRes.status})`);
    const human = await okRes.json();
    assert(human.request_id === requestId, "HumanResolution.request_id");
    assert(human.resolution === "approve", "HumanResolution.resolution");
    assert(human.rating === "good", "HumanResolution.rating");
    assert(human.value === 450, "HumanResolution.value in euros (450)");
    console.log("   ✓ 200 HumanResolution:", JSON.stringify(human));

    console.log("\n✓ order_flow_smoke PASSED");
  } finally {
    // ── 7. Cleanup ────────────────────────────────────────────────────────────
    console.log("→ cleaning up…");
    if (orgId) {
      await prisma.organization.delete({ where: { id: orgId } }).catch(() => {});
    }
    for (const uid of userIds) {
      await prisma.user.delete({ where: { id: uid } }).catch(() => {});
    }
    const leftover = await prisma.organization.findUnique({ where: { slug } });
    if (leftover) throw new Error("cleanup failed — org still present");
    const leftoverEsc = await prisma.escalation.findUnique({ where: { requestId } });
    if (leftoverEsc) throw new Error("cleanup failed — escalation still present");
    console.log("   ✓ DB clean");

    // Tear down spawned servers.
    if (web && !web.killed) web.kill("SIGKILL");
    if (supervisor && !supervisor.killed) supervisor.kill("SIGKILL");
  }
}

main()
  .catch((e) => {
    console.error("\n✗ order_flow_smoke FAILED:", e);
    process.exitCode = 1;
  })
  .finally(async () => {
    await prisma.$disconnect();
    // give killed children a moment, then force-exit so a lingering handle
    // doesn't keep the process alive.
    setTimeout(() => process.exit(process.exitCode ?? 0), 500);
  });
