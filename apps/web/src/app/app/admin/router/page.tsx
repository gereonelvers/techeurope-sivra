import { redirect } from "next/navigation";
import { requireSession, activeOrg, canManageOrg } from "@/lib/org";
import {
  getRouterConfig,
  sampleCountSinceWatermark,
  listTrainingRuns,
} from "@/lib/router_config";
import { RouterAdmin } from "./RouterAdmin";

// Admin · Router model page. OWNER/ADMIN only — RouterConfig is a global singleton
// (the live delegation-router model + auto-retrain knobs), so we gate on the
// caller's active-org RBAC. Shows the active model + version, resolved-feedback
// count since the last train vs the threshold, the ModelTrainingRun history, the
// auto-retrain toggle + threshold editor, and a "Retrain now" button.
export const dynamic = "force-dynamic";

export default async function RouterAdminPage() {
  const session = await requireSession();
  const active = await activeOrg(session);
  if (!active) return null;
  if (!canManageOrg(active.role)) {
    // view-only members can't manage the global router
    redirect("/app");
  }

  const [config, sampleCount, runs] = await Promise.all([
    getRouterConfig(),
    sampleCountSinceWatermark(),
    listTrainingRuns(20),
  ]);

  const runRows = runs.map((r) => ({
    id: r.id,
    startedAt: r.startedAt.toISOString(),
    finishedAt: r.finishedAt ? r.finishedAt.toISOString() : null,
    status: r.status,
    triggeredBy: r.triggeredBy,
    sampleCount: r.sampleCount,
    championModelId: r.championModelId,
    challengerModelId: r.challengerModelId,
    championScores: (r.championScores as Record<string, number> | null) ?? null,
    challengerScores: (r.challengerScores as Record<string, number> | null) ?? null,
    decision: r.decision,
    notes: r.notes,
  }));

  return (
    <div>
      <header className="border-b border-ink/10 pb-6">
        <h1 className="text-3xl font-semibold">Router model</h1>
        <p className="mt-2 max-w-prose text-sm leading-relaxed text-ink/60">
          The fine-tuned delegation router that decides whom to ping and how
          urgently. It retrains daily from resolved feedback, is evaluated against
          the live champion on a held-out set, and is promoted by a single DB write
          — no redeploy. This page is the control panel for that loop.
        </p>
      </header>

      <RouterAdmin
        initialConfig={{
          activeModelId: config.activeModelId,
          baseModel: config.baseModel,
          version: config.version,
          autoRetrainEnabled: config.autoRetrainEnabled,
          minSamples: config.minSamples,
          lastTrainedAt: config.lastTrainedAt ? config.lastTrainedAt.toISOString() : null,
          lastTrainedSampleCount: config.lastTrainedSampleCount,
        }}
        sampleCount={sampleCount}
        runs={runRows}
      />
    </div>
  );
}
