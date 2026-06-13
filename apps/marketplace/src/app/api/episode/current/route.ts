import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { fromJson } from "@/lib/json";
import { getEpisodeId } from "@/lib/session";

export const dynamic = "force-dynamic";

// GET /api/episode/current -> the current episode (from cookie), with parsed
// taskSpec / targetAttrs, or { episodeId: null }.
export async function GET() {
  const episodeId = getEpisodeId();
  if (!episodeId) {
    return NextResponse.json({ episodeId: null });
  }

  const episode = await prisma.episode.findUnique({
    where: { id: episodeId },
  });

  if (!episode) {
    return NextResponse.json({ episodeId: null });
  }

  return NextResponse.json({
    episodeId: episode.id,
    site: episode.site,
    taskSpec: fromJson(episode.taskSpec),
    targetItemId: episode.targetItemId,
    targetAttrs: fromJson(episode.targetAttrs),
    createdAt: episode.createdAt,
  });
}
