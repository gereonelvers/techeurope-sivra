import { NextRequest } from "next/server";

/**
 * Guard for routes under /api/internal/* and /api/voice/* that are called by
 * the Python services (orchestrator, supervisor, elevenlabs-voice) rather than
 * the browser. They authenticate with a shared secret in the `x-internal-token`
 * header. Throws InternalAuthError on mismatch; route handlers should catch it
 * and return 401.
 */
export class InternalAuthError extends Error {
  status = 401 as const;
  constructor(message = "Unauthorized: invalid internal token") {
    super(message);
    this.name = "InternalAuthError";
  }
}

export function assertInternal(req: NextRequest | Request): void {
  const expected = process.env.INTERNAL_API_TOKEN;
  if (!expected) {
    throw new InternalAuthError("INTERNAL_API_TOKEN is not configured");
  }
  const provided = req.headers.get("x-internal-token");
  if (!provided || provided !== expected) {
    throw new InternalAuthError();
  }
}
