import { PrismaClient } from "@prisma/client";
import { computeReward } from "../src/lib/reward";
import { computeTarget } from "../src/lib/target";
import { toJson } from "../src/lib/json";
import { TaskSpec } from "../src/lib/types";

// End-to-end smoke test of the episode -> events -> reward pipeline. Calls the
// SAME reward function the /api/reward route uses (src/lib/reward.ts), so the
// oracle is verified directly. Run with: npm run smoke
//
// NOTE: src/lib/target.ts imports the shared prisma singleton from src/lib/db,
// which reads DATABASE_URL relative to the schema's ./dev.db. We construct our
// own client here for inserting events/episodes for symmetry with the API.

const prisma = new PrismaClient();

let failures = 0;

function assert(cond: boolean, msg: string) {
  if (cond) {
    console.log(`  PASS  ${msg}`);
  } else {
    failures++;
    console.error(`  FAIL  ${msg}`);
  }
}

// Append an event with the correct incrementing step (mirrors emitEvent).
async function addEvent(
  episodeId: string,
  site: string,
  type: string,
  payload: Record<string, unknown>,
) {
  const last = await prisma.event.findFirst({
    where: { episodeId },
    orderBy: { step: "desc" },
    select: { step: true },
  });
  const step = (last?.step ?? 0) + 1;
  await prisma.event.create({
    data: { episodeId, site, step, type, payload: toJson(payload) },
  });
}

async function loadEpisodeAndEvents(episodeId: string) {
  const episode = await prisma.episode.findUniqueOrThrow({
    where: { id: episodeId },
  });
  const events = await prisma.event.findMany({
    where: { episodeId },
    orderBy: { step: "asc" },
  });
  return { episode, events };
}

async function createEpisode(site: string, taskSpec: TaskSpec) {
  const { targetItemId, targetAttrs } = await computeTarget(site, taskSpec);
  const episode = await prisma.episode.create({
    data: {
      site,
      taskSpec: toJson(taskSpec),
      targetItemId: targetItemId ?? null,
      targetAttrs: targetAttrs ? toJson(targetAttrs) : null,
    },
  });
  return { episode, targetItemId, targetAttrs };
}

async function run() {
  console.log("SMOKE: marketplace reward pipeline\n");

  const site = "site-a";
  // A concrete task: cheapest Laptop under €1500.
  const taskSpec: TaskSpec = {
    category: "Laptops",
    maxPriceCents: 150000,
  };

  // ---------------------------------------------------------------------
  // Scenario 1: order the CORRECT (target) item -> success, scalar > 0.9
  // ---------------------------------------------------------------------
  console.log("Scenario 1: order the target item");
  const { episode, targetItemId, targetAttrs } = await createEpisode(
    site,
    taskSpec,
  );
  assert(targetItemId != null, `target computed (id=${targetItemId})`);
  if (targetItemId == null || targetAttrs == null) {
    throw new Error("no target found for task; is the DB seeded?");
  }

  // Walk the full funnel, ending in ORDER_PLACED of the target item.
  await addEvent(episode.id, site, "SEARCH_SUBMITTED", { query: "laptop" });
  await addEvent(episode.id, site, "FILTER_APPLIED", {
    facet: "category",
    value: "Laptops",
  });
  await addEvent(episode.id, site, "FILTER_APPLIED", {
    facet: "maxPrice",
    value: "1500",
  });
  await addEvent(episode.id, site, "PRODUCT_VIEWED", { itemId: targetItemId });
  await addEvent(episode.id, site, "ADD_TO_CART", { itemId: targetItemId });
  await addEvent(episode.id, site, "CHECKOUT_STARTED", {});
  await addEvent(episode.id, site, "ORDER_PLACED", {
    itemId: targetItemId,
    priceCents: targetAttrs.priceCents,
    attrs: targetAttrs,
  });

  {
    const { episode: ep, events } = await loadEpisodeAndEvents(episode.id);
    const reward = computeReward(
      { id: ep.id, targetItemId: ep.targetItemId, targetAttrs: ep.targetAttrs },
      events.map((e) => ({ type: e.type, payload: e.payload, step: e.step })),
    );
    console.log("  reward:", JSON.stringify(reward));
    assert(reward.success === true, "success === true");
    assert(reward.scalar > 0.9, `scalar > 0.9 (got ${reward.scalar})`);
    assert(
      reward.checkpointsHit === reward.checkpointsTotal,
      `all ${reward.checkpointsTotal} checkpoints hit`,
    );
    assert(reward.attrMatch === 1, `attrMatch === 1 (got ${reward.attrMatch})`);
  }

  // ---------------------------------------------------------------------
  // Scenario 2: order the WRONG item -> success === false
  // ---------------------------------------------------------------------
  console.log("\nScenario 2: order a different (wrong) item");
  const { episode: ep2 } = await createEpisode(site, taskSpec);

  // Find a clearly-wrong item: an expensive Laptop that is NOT the target.
  const wrong = await prisma.listing.findFirst({
    where: { site, category: "Laptops", id: { not: targetItemId } },
    orderBy: { priceCents: "desc" },
  });
  if (!wrong) throw new Error("could not find a wrong item");
  assert(wrong.id !== targetItemId, `wrong item differs (id=${wrong.id})`);

  await addEvent(ep2.id, site, "SEARCH_SUBMITTED", { query: "laptop" });
  await addEvent(ep2.id, site, "FILTER_APPLIED", {
    facet: "category",
    value: "Laptops",
  });
  await addEvent(ep2.id, site, "PRODUCT_VIEWED", { itemId: wrong.id });
  await addEvent(ep2.id, site, "ADD_TO_CART", { itemId: wrong.id });
  await addEvent(ep2.id, site, "CHECKOUT_STARTED", {});
  await addEvent(ep2.id, site, "ORDER_PLACED", {
    itemId: wrong.id,
    priceCents: wrong.priceCents,
    attrs: {
      category: wrong.category,
      brand: wrong.brand,
      condition: wrong.condition,
      priceCents: wrong.priceCents,
      city: wrong.city,
    },
  });

  {
    const { episode: ep, events } = await loadEpisodeAndEvents(ep2.id);
    const reward = computeReward(
      { id: ep.id, targetItemId: ep.targetItemId, targetAttrs: ep.targetAttrs },
      events.map((e) => ({ type: e.type, payload: e.payload, step: e.step })),
    );
    console.log("  reward:", JSON.stringify(reward));
    assert(reward.success === false, "success === false (wrong item)");
    assert(reward.scalar < 0.9, `scalar < 0.9 (got ${reward.scalar})`);
    // It still ordered a Laptop, so category matches but it should NOT be a
    // full success.
    assert(
      reward.checkpointsHit === reward.checkpointsTotal,
      "funnel still complete (checkpoints hit) even though wrong item",
    );
  }

  // Cleanup the smoke episodes so reseeding isn't required between runs.
  await prisma.event.deleteMany({
    where: { episodeId: { in: [episode.id, ep2.id] } },
  });
  await prisma.episode.deleteMany({
    where: { id: { in: [episode.id, ep2.id] } },
  });

  console.log(
    `\nSMOKE ${failures === 0 ? "PASSED" : "FAILED"} (${failures} failure(s))`,
  );
}

run()
  .catch((e) => {
    console.error("SMOKE crashed:", e);
    process.exitCode = 1;
  })
  .finally(async () => {
    await prisma.$disconnect();
    if (failures > 0) process.exitCode = 1;
  });
