// Delegation-router model config + retrain audit — the server-side helpers behind
// the DB-backed active model. Promotion is a no-redeploy DB write: bump
// RouterConfig.activeModelId and live routing (api/internal/escalations → supervisor
// /route with `model`) picks it up on the next request.
//
// apps/web is the only writer of the product DB (ARCHITECTURE.md), so the cron
// orchestrator drives all of this through the internal HTTP endpoints below, which
// in turn call these helpers.

import { prisma } from "@/lib/db";
import { Prisma } from "@prisma/client";

// Fallback used only if the singleton row is somehow missing (it's seeded by
// prisma/seed-router-config.mjs). Keeps live routing working rather than throwing.
export const FALLBACK_ACTIVE_MODEL = "1c0bc366-42f1-414f-86ed-1ee503f2bbc4";
export const DEFAULT_BASE_MODEL = "Qwen/Qwen3-4B-Instruct-2507";

export interface RouterConfigView {
  id: string;
  activeModelId: string;
  baseModel: string;
  version: number;
  autoRetrainEnabled: boolean;
  minSamples: number;
  lastTrainedAt: Date | null;
  lastTrainedSampleCount: number;
  updatedAt: Date;
}

/**
 * Read (self-healing) the singleton RouterConfig. If no row exists yet we create
 * one pointing at the champion so the app is always routable. Global, not
 * org-scoped: there is exactly one live router model across the platform.
 */
export async function getRouterConfig(): Promise<RouterConfigView> {
  const existing = await prisma.routerConfig.findFirst({
    orderBy: { updatedAt: "asc" },
  });
  if (existing) return existing;
  return prisma.routerConfig.create({
    data: { activeModelId: FALLBACK_ACTIVE_MODEL, baseModel: DEFAULT_BASE_MODEL },
  });
}

/** The active Pioneer model id for live routing — passed to supervisor /route. */
export async function getActiveRouterModel(): Promise<string> {
  try {
    const cfg = await getRouterConfig();
    return cfg.activeModelId || FALLBACK_ACTIVE_MODEL;
  } catch {
    // Never break the escalation path on a config read error.
    return FALLBACK_ACTIVE_MODEL;
  }
}

/**
 * Resolved-feedback count since the last successful train (the retrain trigger
 * signal). "Resolved feedback" = Escalation rows with status RESOLVED created
 * after RouterConfig.lastTrainedAt (or all-time if never trained). These are the
 * rows feedback_dataset.py turns into new SFT examples.
 */
export async function sampleCountSinceWatermark(): Promise<number> {
  const cfg = await getRouterConfig();
  const where: Prisma.EscalationWhereInput = { status: "RESOLVED" };
  if (cfg.lastTrainedAt) where.resolvedAt = { gt: cfg.lastTrainedAt };
  return prisma.escalation.count({ where });
}

export interface RouterStateView {
  activeModelId: string;
  baseModel: string;
  version: number;
  autoRetrainEnabled: boolean;
  minSamples: number;
  lastTrainedAt: string | null;
  lastTrainedSampleCount: number;
  sampleCount: number; // resolved-feedback since watermark
}

/** The full state the cron + admin page read from GET /api/internal/router/state. */
export async function getRouterState(): Promise<RouterStateView> {
  const cfg = await getRouterConfig();
  const sampleCount = await sampleCountSinceWatermark();
  return {
    activeModelId: cfg.activeModelId,
    baseModel: cfg.baseModel,
    version: cfg.version,
    autoRetrainEnabled: cfg.autoRetrainEnabled,
    minSamples: cfg.minSamples,
    lastTrainedAt: cfg.lastTrainedAt ? cfg.lastTrainedAt.toISOString() : null,
    lastTrainedSampleCount: cfg.lastTrainedSampleCount,
    sampleCount,
  };
}

// ── ModelTrainingRun create/update ───────────────────────────────────────────
export interface TrainingRunInput {
  id?: string; // when present → update that run, else create
  status?: string; // running | succeeded | failed
  triggeredBy?: string; // cron | manual
  sampleCount?: number;
  datasetId?: string | null;
  championModelId?: string | null;
  challengerModelId?: string | null;
  championScores?: Prisma.InputJsonValue | null;
  challengerScores?: Prisma.InputJsonValue | null;
  decision?: string | null; // promoted | kept | failed | skipped
  notes?: string | null;
  finishedAt?: Date | null;
}

/**
 * Create or update a ModelTrainingRun (the retrain audit row). Pass an `id` to
 * update an existing run (e.g. flip running→succeeded with the eval scores), omit
 * it to create a new one. Returns the row id.
 */
export async function recordTrainingRun(input: TrainingRunInput): Promise<{ id: string }> {
  const data: Prisma.ModelTrainingRunUncheckedUpdateInput &
    Prisma.ModelTrainingRunUncheckedCreateInput = {} as never;

  if (input.status !== undefined) data.status = input.status;
  if (input.triggeredBy !== undefined) data.triggeredBy = input.triggeredBy;
  if (input.sampleCount !== undefined) data.sampleCount = input.sampleCount;
  if (input.datasetId !== undefined) data.datasetId = input.datasetId;
  if (input.championModelId !== undefined) data.championModelId = input.championModelId;
  if (input.challengerModelId !== undefined) data.challengerModelId = input.challengerModelId;
  if (input.championScores !== undefined)
    data.championScores = input.championScores ?? Prisma.DbNull;
  if (input.challengerScores !== undefined)
    data.challengerScores = input.challengerScores ?? Prisma.DbNull;
  if (input.decision !== undefined) data.decision = input.decision;
  if (input.notes !== undefined) data.notes = input.notes;
  if (input.finishedAt !== undefined) data.finishedAt = input.finishedAt;

  if (input.id) {
    const updated = await prisma.modelTrainingRun.update({
      where: { id: input.id },
      data,
      select: { id: true },
    });
    return updated;
  }
  const created = await prisma.modelTrainingRun.create({
    data: { status: input.status ?? "running", ...data },
    select: { id: true },
  });
  return created;
}

/**
 * Promote a challenger to champion — a single DB write. Sets activeModelId, bumps
 * version, and watermarks lastTrainedAt/lastTrainedSampleCount so the next
 * trigger only counts feedback gathered AFTER this train. Live routing picks the
 * new model up immediately (no redeploy). Returns the new {activeModelId, version}.
 */
export async function promoteModel(
  modelId: string,
  opts: { sampleCount?: number } = {},
): Promise<{ activeModelId: string; version: number }> {
  const cfg = await getRouterConfig();
  const updated = await prisma.routerConfig.update({
    where: { id: cfg.id },
    data: {
      activeModelId: modelId,
      version: { increment: 1 },
      lastTrainedAt: new Date(),
      lastTrainedSampleCount: opts.sampleCount ?? cfg.lastTrainedSampleCount,
    },
    select: { activeModelId: true, version: true },
  });
  return updated;
}

/**
 * Watermark a train WITHOUT changing the active model (the "kept" path): the
 * challenger lost the eval, but we still trained on the latest feedback, so reset
 * the sample-count baseline to avoid retraining on the same rows tomorrow.
 */
export async function markTrained(sampleCount: number): Promise<void> {
  const cfg = await getRouterConfig();
  await prisma.routerConfig.update({
    where: { id: cfg.id },
    data: { lastTrainedAt: new Date(), lastTrainedSampleCount: sampleCount },
  });
}

/** Patch the auto-retrain knobs from the admin page (enable toggle + threshold). */
export async function updateRouterConfig(patch: {
  autoRetrainEnabled?: boolean;
  minSamples?: number;
}): Promise<RouterConfigView> {
  const cfg = await getRouterConfig();
  return prisma.routerConfig.update({
    where: { id: cfg.id },
    data: {
      ...(patch.autoRetrainEnabled !== undefined
        ? { autoRetrainEnabled: patch.autoRetrainEnabled }
        : {}),
      ...(patch.minSamples !== undefined
        ? { minSamples: Math.max(0, Math.round(patch.minSamples)) }
        : {}),
    },
  });
}

/** Recent ModelTrainingRun history for the admin page (newest first). */
export async function listTrainingRuns(limit = 20) {
  return prisma.modelTrainingRun.findMany({
    orderBy: { startedAt: "desc" },
    take: limit,
  });
}
