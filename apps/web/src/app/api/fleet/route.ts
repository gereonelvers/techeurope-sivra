import { NextResponse } from "next/server";

// GET /api/fleet — same-origin proxy for the deployed Mission Control fleet feed
// (GET ${MISSION_CONTROL_URL}/api/fleet). The browser polls THIS so it never has
// to reach the standalone service cross-origin. We also rewrite each agent's
// relative `screenshot_url` to an absolute Mission Control URL so the <img> in
// the grid loads the thumbnail directly from MC.
//
// Always returns 200 with a normalized shape; on upstream error/empty it returns
// { agents: [], ok:false, … } so the client can render a graceful "fleet idle".
export const dynamic = "force-dynamic";
export const revalidate = 0;

const DEFAULT_MISSION_CONTROL_URL =
  "https://mission-control-production-332c.up.railway.app";

function missionControlBase(): string {
  return (process.env.MISSION_CONTROL_URL || DEFAULT_MISSION_CONTROL_URL).replace(
    /\/$/,
    "",
  );
}

interface FleetAgent {
  agent_id?: string;
  site?: string;
  screenshot_url?: string | null;
  action?: string | null;
  goal?: string | null;
  category?: string | null;
  status?: string | null;
  step?: number | null;
  n_steps?: number | null;
  reward?: number | null;
  success?: boolean | null;
  [k: string]: unknown;
}

interface FleetResponse {
  agents?: FleetAgent[];
  stats?: unknown;
  tick?: unknown;
  source?: unknown;
  [k: string]: unknown;
}

/** Make a possibly-relative screenshot path absolute against the MC base.
 * Live agents embed the frame as a self-contained `data:` URI (blobs are
 * self-contained too) — those must pass through untouched. Only genuinely
 * relative paths (e.g. `/shots/…`) get the MC base prepended. */
function absolutize(url: string | null | undefined, base: string): string | null {
  if (!url) return null;
  if (/^(https?:|data:|blob:)/i.test(url)) return url;
  return `${base}${url.startsWith("/") ? "" : "/"}${url}`;
}

export async function GET() {
  const base = missionControlBase();
  try {
    const res = await fetch(`${base}/api/fleet`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
      // A Deep run's snapshot (up to ~24 embedded frames) is a few MB — give the
      // upstream fetch a bit more headroom than a small fleet would need.
      signal: AbortSignal.timeout(10000),
    });
    if (!res.ok) {
      return NextResponse.json(
        { ok: false, agents: [], missionControlUrl: base, error: `upstream ${res.status}` },
        { status: 200 },
      );
    }
    const data = (await res.json()) as FleetResponse;
    const agents = Array.isArray(data.agents) ? data.agents : [];
    const normalized = agents.map((a) => ({
      ...a,
      screenshot_url: absolutize(a.screenshot_url, base),
    }));
    return NextResponse.json(
      {
        ok: true,
        agents: normalized,
        stats: data.stats ?? null,
        tick: data.tick ?? null,
        source: data.source ?? null,
        missionControlUrl: base,
      },
      { status: 200 },
    );
  } catch (err) {
    // Unreachable / timeout → graceful idle (200, empty agents).
    return NextResponse.json(
      {
        ok: false,
        agents: [],
        missionControlUrl: base,
        error: String(err instanceof Error ? err.message : err),
      },
      { status: 200 },
    );
  }
}
