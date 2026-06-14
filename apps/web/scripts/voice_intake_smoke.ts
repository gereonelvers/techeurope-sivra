// Inbound-voice intake smoke test. Run with:
//   DISPATCH_DRY_RUN=1 npx tsx scripts/voice_intake_smoke.ts
//
// Exercises the REAL POST /api/voice/intake route against the real DB:
//   0. start the Next.js standalone server on a free port (no supervisor needed —
//      launchOrder only flips status + best-effort orchestrator, which we disable)
//   1. seed an org + a user whose `phone` is set (E.164). Also seed the DEMO
//      caller (QM_DEMO_PHONE from the env) so a live inbound call resolves.
//   2. POST a simulated intake from the seeded phone (in a "messy" format, no +)
//      → assert an Order is created under that user's org, VOICE channel,
//        requestedById = the seeded user, status launched to SEARCHING.
//   3. POST a simulated intake from an UNKNOWN caller → assert it falls back to
//      DEFAULT_VOICE_ORG_ID (we point it at our seeded org) with requestedById
//      null and an "unverified caller" audit note.
//   4. delete every row created; verify the DB is clean.
//
// Nothing is deployed; no SMS/calls/emails (orchestrator disabled, dispatch is
// not on this path anyway).
import { spawn, type ChildProcess } from "child_process";
import { createServer } from "net";
import { readFileSync } from "fs";
import path from "path";

const REPO_ROOT = path.resolve(__dirname, "../../..");
const WEB_ROOT = path.resolve(__dirname, "..");

// Minimal dotenv that never clobbers an already-set value. We load apps/web/.env
// (for DATABASE_URL / INTERNAL_API_TOKEN) AND the repo-root .env (for QM_DEMO_PHONE).
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
loadDotenv(path.join(REPO_ROOT, ".env"));

import { prisma } from "@/lib/db";

const INTERNAL_TOKEN = process.env.INTERNAL_API_TOKEN ?? "smoke-internal-token";
// The real demo caller (so a live inbound call from this phone resolves). Falls
// back to a fixed E.164 if QM_DEMO_PHONE isn't present in the env.
const DEMO_PHONE = (process.env.QM_DEMO_PHONE ?? "+14155550123").trim();

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
  const slug = `voice-smoke-${stamp}`;

  let web: ChildProcess | null = null;
  let orgId: string | null = null;
  const userIds: string[] = [];
  const orderIds: string[] = [];

  try {
    // ── 0. Seed org + a phone-bearing user (BEFORE starting the server so the
    //       fallback "first org" / DEFAULT_VOICE_ORG_ID resolves to ours). ──────
    console.log("→ seeding org + demo caller…");
    const { defaultPolicyCreate } = await import("@/lib/policy");
    const org = await prisma.organization.create({
      data: {
        name: "Voice Smoke Org",
        slug,
        policies: { create: defaultPolicyCreate() },
      },
    });
    orgId = org.id;

    // The demo caller — phone set to QM_DEMO_PHONE so a real inbound call resolves.
    const callerUser = await prisma.user.create({
      data: {
        email: `caller+${stamp}@example.com`,
        name: "Demo Caller",
        phone: DEMO_PHONE,
      },
    });
    userIds.push(callerUser.id);
    await prisma.membership.create({
      data: {
        orgId: org.id,
        userId: callerUser.id,
        role: "OWNER",
        purchasingRole: "manager",
      },
    });

    // ── 0b. Start the Next standalone server. DEFAULT_VOICE_ORG_ID → our org so
    //         the no-match fallback is deterministic (not some other DB org). ────
    const webPort = await freePort();
    const webUrl = `http://127.0.0.1:${webPort}`;
    console.log(`→ starting Next app (standalone server) on :${webPort}…`);
    web = spawn("node", [path.join(WEB_ROOT, ".next/standalone/server.js")], {
      cwd: WEB_ROOT,
      stdio: ["ignore", "inherit", "inherit"],
      env: {
        ...process.env,
        PORT: String(webPort),
        HOSTNAME: "127.0.0.1",
        AUTH_URL: webUrl,
        INTERNAL_API_TOKEN: INTERNAL_TOKEN,
        DEFAULT_VOICE_ORG_ID: org.id,
        DISPATCH_DRY_RUN: "1",
        ORCHESTRATOR_URL: "", // no orchestrator kick
      },
    });
    await waitForHttp(`${webUrl}/api/internal/ping`, "web", 90000, {
      "x-internal-token": INTERNAL_TOKEN,
    });
    console.log("   ✓ app up");

    const internalHeaders = {
      "Content-Type": "application/json",
      "x-internal-token": INTERNAL_TOKEN,
    };

    // ── 1. Matched-caller path: phone in a messy format (no "+", spaces). ──────
    console.log("→ POST /api/voice/intake (known caller)…");
    const messyPhone = DEMO_PHONE.replace(/^\+/, "").replace(/(\d{3})(\d)/, "$1 $2");
    const res1 = await fetch(`${webUrl}/api/voice/intake`, {
      method: "POST",
      headers: internalHeaders,
      body: JSON.stringify({
        callerPhone: messyPhone,
        title: "Ergonomic office chair",
        description: "Mesh back, lumbar support, for the new design hire",
        maxBudgetCents: 45000,
        currency: "EUR",
      }),
    });
    assert(res1.ok, `voice/intake (known) returned ${res1.status}`);
    const body1 = (await res1.json()) as { orderId?: string; status?: string };
    console.log("   →", JSON.stringify(body1));
    assert(body1.orderId, "orderId returned");
    orderIds.push(body1.orderId!);

    const order1 = await prisma.order.findUnique({ where: { id: body1.orderId! } });
    assert(order1, "order persisted (known caller)");
    assert(order1!.orgId === org.id, "order is scoped to the caller's org");
    assert(order1!.intakeChannel === "VOICE", "intakeChannel is VOICE");
    assert(order1!.requestedById === callerUser.id, "requestedById = the matched user");
    assert(order1!.title === "Ergonomic office chair", "title set");
    assert(order1!.maxBudgetCents === 45000, "maxBudgetCents kept as integer cents");
    assert(order1!.status === "SEARCHING", `order launched to SEARCHING (got ${order1!.status})`);

    const events1 = await prisma.orderEvent.findMany({
      where: { orderId: order1!.id },
      orderBy: { createdAt: "asc" },
    });
    const types1 = events1.map((e) => e.type);
    assert(types1.includes("created"), "created audit event present");
    assert(types1.includes("search_started"), "search_started audit event present");
    const note1 = events1.find((e) => e.type === "note");
    assert(note1 && note1.actorType === "user", "verified-caller note attributed to user");
    console.log("   ✓ known caller → order in their org, VOICE, requestedById set, launched");

    // ── 2. No-match fallback path: unknown caller → DEFAULT_VOICE_ORG_ID. ──────
    console.log("→ POST /api/voice/intake (unknown caller, fallback)…");
    const res2 = await fetch(`${webUrl}/api/voice/intake`, {
      method: "POST",
      headers: internalHeaders,
      body: JSON.stringify({
        callerPhone: "+19998887777",
        title: "Box of printer paper",
        maxBudgetCents: 2500,
        currency: "EUR",
      }),
    });
    assert(res2.ok, `voice/intake (unknown) returned ${res2.status}`);
    const body2 = (await res2.json()) as { orderId?: string; status?: string };
    console.log("   →", JSON.stringify(body2));
    assert(body2.orderId, "orderId returned (fallback)");
    orderIds.push(body2.orderId!);

    const order2 = await prisma.order.findUnique({ where: { id: body2.orderId! } });
    assert(order2, "order persisted (fallback)");
    assert(order2!.orgId === org.id, "fallback order attached to DEFAULT_VOICE_ORG_ID org");
    assert(order2!.intakeChannel === "VOICE", "fallback intakeChannel is VOICE");
    assert(order2!.requestedById === null, "fallback requestedById is null (unverified)");

    const events2 = await prisma.orderEvent.findMany({
      where: { orderId: order2!.id },
      orderBy: { createdAt: "asc" },
    });
    const note2 = events2.find((e) => e.type === "note");
    assert(note2, "fallback note event present");
    assert(
      (note2!.message ?? "").toLowerCase().includes("unverified caller"),
      `fallback note flags 'unverified caller' (got: ${note2!.message})`,
    );
    assert(note2!.actorType === "system", "unverified note attributed to system");
    console.log("   ✓ unknown caller → fallback org, requestedById null, unverified note");

    console.log("\n✓ voice_intake_smoke PASSED");
  } finally {
    // ── Cleanup ────────────────────────────────────────────────────────────────
    console.log("→ cleaning up…");
    for (const oid of orderIds) {
      await prisma.order.delete({ where: { id: oid } }).catch(() => {});
    }
    if (orgId) {
      await prisma.organization.delete({ where: { id: orgId } }).catch(() => {});
    }
    for (const uid of userIds) {
      await prisma.user.delete({ where: { id: uid } }).catch(() => {});
    }
    const leftover = await prisma.organization.findUnique({ where: { slug } });
    if (leftover) throw new Error("cleanup failed — org still present");
    for (const oid of orderIds) {
      const o = await prisma.order.findUnique({ where: { id: oid } });
      if (o) throw new Error("cleanup failed — order still present");
    }
    console.log("   ✓ DB clean");

    if (web && !web.killed) web.kill("SIGKILL");
  }
}

main()
  .catch((e) => {
    console.error("\n✗ voice_intake_smoke FAILED:", e);
    process.exitCode = 1;
  })
  .finally(async () => {
    await prisma.$disconnect();
    setTimeout(() => process.exit(process.exitCode ?? 0), 500);
  });
