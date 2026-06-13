import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { toJson } from "@/lib/json";
import { computeTarget } from "@/lib/target";
import { setEpisodeId } from "@/lib/session";
import { isSite, TaskSpec } from "@/lib/types";

export const dynamic = "force-dynamic";

// POST /api/episode  { site, taskSpec } -> create Episode, compute target,
// set episode_id cookie, return { episodeId, targetItemId }.
export async function POST(req: NextRequest) {
  let body: { site?: string; taskSpec?: TaskSpec };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }

  const site = body.site;
  const taskSpec = body.taskSpec;

  if (!site || !isSite(site)) {
    return NextResponse.json(
      { error: "site must be one of site-a | site-b | site-c" },
      { status: 400 },
    );
  }
  if (!taskSpec || typeof taskSpec !== "object") {
    return NextResponse.json(
      { error: "taskSpec object required" },
      { status: 400 },
    );
  }

  const { targetItemId, targetAttrs } = await computeTarget(site, taskSpec);

  const episode = await prisma.episode.create({
    data: {
      site,
      taskSpec: toJson(taskSpec),
      targetItemId: targetItemId ?? null,
      targetAttrs: targetAttrs ? toJson(targetAttrs) : null,
    },
  });

  // Set the episode cookie so subsequent buyer actions attach to this episode.
  setEpisodeId(episode.id);

  return NextResponse.json({
    episodeId: episode.id,
    targetItemId,
    targetAttrs,
    site,
    taskSpec,
  });
}
