import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { computeReward } from "@/lib/reward";
import { fromJson } from "@/lib/json";
import { getEpisodeId } from "@/lib/session";

export const dynamic = "force-dynamic";

// GET /api/reward?episodeId=... -> structured reward by replaying the episode's
// events. Agent-agnostic: reads only persisted events + the episode target.
// Falls back to the current episode cookie if no episodeId is supplied.
export async function GET(req: NextRequest) {
  const episodeId =
    req.nextUrl.searchParams.get("episodeId") ?? getEpisodeId();

  if (!episodeId) {
    return NextResponse.json(
      { error: "episodeId required (query param or episode_id cookie)" },
      { status: 400 },
    );
  }

  const episode = await prisma.episode.findUnique({
    where: { id: episodeId },
  });

  if (!episode) {
    return NextResponse.json(
      { error: `episode ${episodeId} not found` },
      { status: 404 },
    );
  }

  const events = await prisma.event.findMany({
    where: { episodeId },
    orderBy: { step: "asc" },
  });

  const reward = computeReward(
    {
      id: episode.id,
      targetItemId: episode.targetItemId,
      targetAttrs: episode.targetAttrs,
    },
    events.map((e) => ({ type: e.type, payload: e.payload, step: e.step })),
  );

  return NextResponse.json({
    episodeId: episode.id,
    site: episode.site,
    targetItemId: episode.targetItemId,
    taskSpec: fromJson(episode.taskSpec),
    ...reward,
    events: events.map((e) => ({
      step: e.step,
      type: e.type,
      payload: fromJson(e.payload),
    })),
  });
}
