import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { assertInternal, InternalAuthError } from "@/lib/internal";
import {
  resolveEscalation,
  EscalationNotFoundError,
  type ResolutionKind,
  type Rating,
} from "@/lib/resolve";

// POST /api/voice/resolve — the ElevenLabs ConvAI tool target. Static URL; the
// request_id travels in the body (webhook tools hit a fixed URL). Guarded by
// x-internal-token. Resolves an escalation via the shared write path.
//
// Body: { request_id, resolution, value?, notes?, rating?,
//         correctedRole?, correctedUrgency?, resolvedByLabel? }
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
    request_id?: string;
    resolution?: string;
    value?: number | null;
    notes?: string | null;
    rating?: string | null;
    correctedRole?: string | null;
    correctedUrgency?: string | null;
    resolvedByLabel?: string | null;
  };

  const requestId = String(body.request_id ?? "").trim();
  if (!requestId) {
    return NextResponse.json({ error: "request_id required" }, { status: 422 });
  }
  const resolution = normalizeResolution(body.resolution);
  if (!resolution) {
    return NextResponse.json(
      { error: "resolution must be approve|counter|decline" },
      { status: 422 },
    );
  }

  // schema.py HumanResolution carries `value` in EUROS (float); the app's
  // internal unit is integer cents. Convert at this boundary.
  const valueCents =
    body.value === undefined || body.value === null
      ? null
      : Math.round(Number(body.value) * 100);

  try {
    const result = await resolveEscalation({
      codeOrRequestId: requestId,
      resolution,
      value: valueCents,
      notes: body.notes ?? null,
      rating: normalizeRating(body.rating),
      correctedRole: body.correctedRole ?? null,
      correctedUrgency: body.correctedUrgency ?? null,
      resolvedByLabel: body.resolvedByLabel ?? "voice",
    });
    return NextResponse.json({
      ok: true,
      alreadyResolved: result.alreadyResolved,
      status: result.escalation.status,
      orderStatus: result.orderStatus,
      rewardScalar: result.escalation.rewardScalar,
    });
  } catch (err) {
    if (err instanceof EscalationNotFoundError) {
      return NextResponse.json({ error: err.message }, { status: 404 });
    }
    throw err;
  }
}

function normalizeResolution(v: string | undefined): ResolutionKind | null {
  const r = (v ?? "").toLowerCase();
  if (r === "approve" || r === "counter" || r === "decline") return r;
  return null;
}

function normalizeRating(v: string | null | undefined): Rating | null {
  const r = (v ?? "").toLowerCase();
  if (r === "good" || r === "partial" || r === "wrong") return r;
  return null;
}
