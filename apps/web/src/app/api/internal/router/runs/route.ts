import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import type { Prisma } from "@prisma/client";
import { assertInternal, InternalAuthError } from "@/lib/internal";
import { recordTrainingRun } from "@/lib/router_config";

// POST /api/internal/router/runs — create or update a ModelTrainingRun (the
// retrain audit row). The cron creates a `running` row, then updates it with the
// dataset id, champion/challenger model ids, eval scores, and the final decision.
// Pass an `id` to update; omit it to create. Guarded by x-internal-token.
//
// Body: { id?, status?, triggeredBy?, sampleCount?, datasetId?, championModelId?,
//         challengerModelId?, championScores?, challengerScores?, decision?,
//         notes?, finishedAt? (ISO string|null) }
export async function POST(req: NextRequest) {
  try {
    assertInternal(req);
  } catch (err) {
    if (err instanceof InternalAuthError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }

  const body = (await req.json().catch(() => ({}))) as {
    id?: string;
    status?: string;
    triggeredBy?: string;
    sampleCount?: number;
    datasetId?: string | null;
    championModelId?: string | null;
    challengerModelId?: string | null;
    championScores?: Prisma.InputJsonValue | null;
    challengerScores?: Prisma.InputJsonValue | null;
    decision?: string | null;
    notes?: string | null;
    finishedAt?: string | null;
  };

  const run = await recordTrainingRun({
    id: body.id,
    status: body.status,
    triggeredBy: body.triggeredBy,
    sampleCount: body.sampleCount,
    datasetId: body.datasetId,
    championModelId: body.championModelId,
    challengerModelId: body.challengerModelId,
    championScores: body.championScores,
    challengerScores: body.challengerScores,
    decision: body.decision,
    notes: body.notes,
    finishedAt:
      body.finishedAt === undefined
        ? undefined
        : body.finishedAt === null
          ? null
          : new Date(body.finishedAt),
  });

  return NextResponse.json({ run }, { status: body.id ? 200 : 201 });
}
