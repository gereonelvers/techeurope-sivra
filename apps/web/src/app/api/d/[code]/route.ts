import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import {
  resolveEscalation,
  EscalationNotFoundError,
  type ResolutionKind,
  type Rating,
} from "@/lib/resolve";

// POST /api/d/:code — the public tokenized reply page submits here. No session;
// the unguessable `code` IS the capability. Resolves via the shared write path.
// Body: { resolution, value?, notes?, rating?, resolvedByLabel? }
export async function POST(
  req: NextRequest,
  { params }: { params: { code: string } },
) {
  const body = (await req.json().catch(() => ({}))) as {
    resolution?: string;
    value?: number | null;
    notes?: string | null;
    rating?: string | null;
    resolvedByLabel?: string | null;
  };

  const resolution = normalizeResolution(body.resolution);
  if (!resolution) {
    return NextResponse.json(
      { error: "resolution must be approve|counter|decline" },
      { status: 422 },
    );
  }

  try {
    const result = await resolveEscalation({
      codeOrRequestId: params.code,
      resolution,
      value: body.value ?? null,
      notes: body.notes ?? null,
      rating: normalizeRating(body.rating),
      resolvedByLabel: body.resolvedByLabel ?? "reply link",
    });
    return NextResponse.json({
      ok: true,
      alreadyResolved: result.alreadyResolved,
      status: result.escalation.status,
      orderStatus: result.orderStatus,
    });
  } catch (err) {
    if (err instanceof EscalationNotFoundError) {
      return NextResponse.json({ error: "Not found" }, { status: 404 });
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
