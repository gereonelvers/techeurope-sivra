// One-off proof that the DB-backed promote loop works end-to-end against the live
// product DB, using the REAL lib functions. Records a ModelTrainingRun with the
// champion-vs-challenger eval scores, promotes the challenger, then RESTORES the
// champion (1c0bc366) so the live router is left unchanged.
//
//   npx tsx scripts/prove-router-db.ts <champion> <challenger> '<champScoresJson>' '<challScoresJson>' <decision>
//
// Safe: it always restores activeModelId to the champion in a finally block.
import {
  getRouterConfig,
  recordTrainingRun,
  promoteModel,
  markTrained,
  getRouterState,
} from "../src/lib/router_config";

const CHAMPION = process.argv[2] ?? "1c0bc366-42f1-414f-86ed-1ee503f2bbc4";
const CHALLENGER = process.argv[3] ?? "3649d82d-357b-44f1-b1d6-f83e80b2f9de";
const champScores = JSON.parse(process.argv[4] ?? "{}");
const challScores = JSON.parse(process.argv[5] ?? "{}");
const decision = process.argv[6] ?? "promoted"; // promoted | kept

async function main() {
  const before = await getRouterConfig();
  console.log(
    `BEFORE: activeModelId=${before.activeModelId} version=${before.version}`,
  );
  const state0 = await getRouterState();
  console.log(`state sampleCount(since watermark)=${state0.sampleCount}`);

  // 1) open a running run
  const { id: runId } = await recordTrainingRun({
    status: "running",
    triggeredBy: "manual",
    sampleCount: state0.sampleCount,
    championModelId: CHAMPION,
    notes: "DB proof — started",
  });
  console.log(`recordTrainingRun(running) -> ${runId}`);

  try {
    if (decision === "promoted") {
      // 2) promote the challenger (real DB write)
      const res = await promoteModel(CHALLENGER, { sampleCount: state0.sampleCount });
      console.log(
        `promoteModel(${CHALLENGER}) -> activeModelId=${res.activeModelId} version=${res.version}`,
      );
    } else {
      await markTrained(state0.sampleCount);
      console.log(`markTrained(${state0.sampleCount}) (kept path)`);
    }

    // 3) finalize the run with the real scores + decision
    await recordTrainingRun({
      id: runId,
      status: "succeeded",
      decision,
      championModelId: CHAMPION,
      challengerModelId: CHALLENGER,
      championScores: champScores,
      challengerScores: challScores,
      notes: "DB proof — finalized",
      finishedAt: new Date(),
    });
    console.log(`recordTrainingRun(succeeded, decision=${decision}) -> ${runId}`);

    const mid = await getRouterConfig();
    console.log(
      `MID: activeModelId=${mid.activeModelId} version=${mid.version} (challenger active)`,
    );
  } finally {
    // 4) RESTORE the champion so the live router is unchanged.
    const restored = await promoteModel(CHAMPION, {
      sampleCount: before.lastTrainedSampleCount,
    });
    console.log(
      `RESTORED: activeModelId=${restored.activeModelId} version=${restored.version}`,
    );
  }

  const after = await getRouterConfig();
  if (after.activeModelId !== CHAMPION) {
    throw new Error(
      `FATAL: champion not restored (active=${after.activeModelId}) — investigate!`,
    );
  }
  console.log("OK: champion restored; DB proof complete.");
}

main()
  .catch((e) => {
    console.error("prove-router-db failed:", e);
    process.exit(1);
  })
  .finally(() => process.exit(0));
