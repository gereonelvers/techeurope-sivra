import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { assertInternal, InternalAuthError } from "@/lib/internal";

// Example internal route. Demonstrates the guard every /api/internal/* and
// /api/voice/* handler must use: the Python services authenticate with the
// shared `x-internal-token` header. Feature agents: copy this try/catch shape.
export async function GET(req: NextRequest) {
  try {
    assertInternal(req);
  } catch (err) {
    if (err instanceof InternalAuthError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }

  return NextResponse.json({ ok: true, service: "web", ts: new Date().toISOString() });
}
