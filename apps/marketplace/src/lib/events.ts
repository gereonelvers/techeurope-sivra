import { prisma } from "./db";
import { toJson } from "./json";
import { EventType } from "./types";

/**
 * Append an Event row for an episode with a monotonically incrementing `step`.
 * Append-only: never updates existing rows.
 *
 * The step is computed as (max step for the episode) + 1. SQLite serializes
 * writes, so this is safe for our single-process dev/demo setup.
 *
 * Returns the created event id, or null if it could not be written (e.g. the
 * episode does not exist) — callers must never crash on a missing episode.
 */
export async function emitEvent(
  episodeId: string,
  site: string,
  type: EventType | string,
  payload: Record<string, unknown> = {},
): Promise<number | null> {
  if (!episodeId) return null;

  try {
    // Ensure the episode exists; if not, silently skip (don't crash buyers).
    const episode = await prisma.episode.findUnique({
      where: { id: episodeId },
      select: { id: true },
    });
    if (!episode) return null;

    const last = await prisma.event.findFirst({
      where: { episodeId },
      orderBy: { step: "desc" },
      select: { step: true },
    });
    const step = (last?.step ?? 0) + 1;

    const event = await prisma.event.create({
      data: {
        episodeId,
        site,
        step,
        type,
        payload: toJson(payload),
      },
      select: { id: true },
    });
    return event.id;
  } catch (err) {
    // Instrumentation must never break the buyer flow.
    console.error("[emitEvent] failed:", err);
    return null;
  }
}

/**
 * Idempotent-ish emit for render-time events (SEARCH_SUBMITTED / FILTER_APPLIED
 * / PRODUCT_VIEWED): avoid spamming duplicate consecutive events when a page is
 * re-rendered with the identical payload. We only suppress when the most recent
 * event for the episode is the exact same type + payload.
 */
export async function emitEventDeduped(
  episodeId: string,
  site: string,
  type: EventType | string,
  payload: Record<string, unknown> = {},
): Promise<number | null> {
  if (!episodeId) return null;
  try {
    const episode = await prisma.episode.findUnique({
      where: { id: episodeId },
      select: { id: true },
    });
    if (!episode) return null;

    const last = await prisma.event.findFirst({
      where: { episodeId },
      orderBy: { step: "desc" },
      select: { type: true, payload: true },
    });
    if (last && last.type === type && last.payload === toJson(payload)) {
      return null; // duplicate consecutive render event; skip.
    }
    return emitEvent(episodeId, site, type, payload);
  } catch (err) {
    console.error("[emitEventDeduped] failed:", err);
    return null;
  }
}
