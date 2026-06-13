import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { emitEvent } from "@/lib/events";
import { getEpisodeId } from "@/lib/session";

export const dynamic = "force-dynamic";

// POST /api/event { type, payload, episodeId? } -> emit an event for the
// current episode (cookie) or an explicit episodeId. Lets the oracle/agent log
// explicitly if needed.
export async function POST(req: NextRequest) {
  let body: {
    type?: string;
    payload?: Record<string, unknown>;
    episodeId?: string;
  };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }

  if (!body.type) {
    return NextResponse.json({ error: "type required" }, { status: 400 });
  }

  const episodeId = body.episodeId ?? getEpisodeId();
  if (!episodeId) {
    return NextResponse.json(
      { error: "no episode (provide episodeId or set episode_id cookie)" },
      { status: 400 },
    );
  }

  const episode = await prisma.episode.findUnique({
    where: { id: episodeId },
    select: { id: true, site: true },
  });
  if (!episode) {
    return NextResponse.json(
      { error: `episode ${episodeId} not found` },
      { status: 404 },
    );
  }

  const eventId = await emitEvent(
    episode.id,
    episode.site,
    body.type,
    body.payload ?? {},
  );

  return NextResponse.json({ ok: true, eventId, episodeId: episode.id });
}
