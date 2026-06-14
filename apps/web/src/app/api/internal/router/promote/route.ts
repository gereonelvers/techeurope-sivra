import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { assertInternal, InternalAuthError } from "@/lib/internal";
import { promoteModel } from "@/lib/router_config";

// POST /api/internal/router/promote { modelId, sampleCount } — promote a
// challenger to champion. A single DB write: sets RouterConfig.activeModelId,
// bumps version, watermarks lastTrainedAt/lastTrainedSampleCount. Live routing
// (api/internal/escalations → supervisor /route `model`) uses it immediately,
// no redeploy. Guarded by x-internal-token.
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
    modelId?: string;
    sampleCount?: number;
  };
  const modelId = String(body.modelId ?? "").trim();
  if (!modelId) {
    return NextResponse.json({ error: "modelId is required" }, { status: 400 });
  }

  const result = await promoteModel(modelId, {
    sampleCount: typeof body.sampleCount === "number" ? body.sampleCount : undefined,
  });
  return NextResponse.json(result, { status: 200 });
}
