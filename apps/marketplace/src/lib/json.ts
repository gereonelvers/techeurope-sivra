// SQLite (via Prisma) has no native JSON type, so Episode.taskSpec /
// Episode.targetAttrs / Event.payload are stored as TEXT. These helpers keep
// (de)serialization in one place so the rest of the app deals in objects.

export function toJson(value: unknown): string {
  return JSON.stringify(value ?? null);
}

export function fromJson<T = unknown>(value: string | null | undefined): T | null {
  if (value == null || value === "") return null;
  try {
    return JSON.parse(value) as T;
  } catch {
    return null;
  }
}
