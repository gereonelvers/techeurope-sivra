import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { assertInternal, InternalAuthError } from "@/lib/internal";
import { toHumanResolution } from "@/lib/resolve";

// GET /api/internal/escalations/:requestId/resolution — the fleet polls this.
// 200 with a HumanResolution-shaped body once the escalation is RESOLVED,
// otherwise 404 (still pending / unknown). Guarded by x-internal-token.
export async function GET(
  req: NextRequest,
  { params }: { params: { requestId: string } },
) {
  try {
    assertInternal(req);
  } catch (err) {
    if (err instanceof InternalAuthError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }

  const esc = await prisma.escalation.findUnique({
    where: { requestId: params.requestId },
  });
  if (!esc || esc.status !== "RESOLVED") {
    return NextResponse.json({ error: "not resolved yet" }, { status: 404 });
  }

  return NextResponse.json(toHumanResolution(esc));
}
