import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { assertInternal, InternalAuthError } from "@/lib/internal";
import { createOrder, appendOrderEvent, launchOrder } from "@/lib/orders";
import { normalizePhoneE164, formatPhoneDisplay } from "@/lib/phone";
import { createProvisionalAccount, issueClaimLink } from "@/lib/phone-link";
import { sendSms } from "@/lib/dispatch";

// POST /api/voice/intake — the inbound-voice order entrypoint. Called by the
// ElevenLabs ConvAI `create_order` tool (static URL, payload in body) with the
// shared x-internal-token. It:
//   1. normalizes the caller_id to E.164 and matches it to a VERIFIED account,
//   2. KNOWN caller  → order goes to their primary (oldest) org, attributed,
//      UNKNOWN caller → a provisional account+org is created on the fly and we
//        text them a claim link to finish sign-up (the order still runs now),
//      NO usable number → DEFAULT_VOICE_ORG_ID / first org (demo never hard-fails),
//   3. creates an Order(intakeChannel:VOICE) + a "created" event,
//   4. launches it (flip → SEARCHING + kick the orchestrator),
//   5. returns { orderId, status, claim? }.
//
// Body: { callerPhone, title, description?, maxBudgetCents, currency }
interface IntakeBody {
  callerPhone?: string;
  title?: string;
  description?: string | null;
  maxBudgetCents?: number | null;
  currency?: string | null;
}

export async function POST(req: NextRequest) {
  try {
    assertInternal(req);
  } catch (err) {
    if (err instanceof InternalAuthError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }

  const body = (await req.json().catch(() => ({}))) as IntakeBody;
  const rawPhone = String(body.callerPhone ?? "").trim();
  const phone = normalizePhoneE164(rawPhone); // E.164 or null
  const title = String(body.title ?? "").trim();
  if (!title) {
    return NextResponse.json({ error: "title is required" }, { status: 422 });
  }
  const maxBudgetCents =
    body.maxBudgetCents == null ? null : Math.max(0, Math.round(Number(body.maxBudgetCents)));
  const currency = (body.currency ?? "EUR").trim().toUpperCase() || "EUR";

  // ── 1. Resolve the caller → org + (maybe) provisional sign-up ───────────────
  let orgId: string | null = null;
  let requestedById: string | null = null;
  let provisional = false; // order lives in a not-yet-claimed provisional account

  if (phone) {
    const match = await resolveVerifiedCaller(phone);
    if (match) {
      // Known number (a real account, OR a provisional one from a prior call).
      orgId = match.orgId;
      requestedById = match.userId;
      provisional = match.isProvisional;
    } else {
      // Unknown number → spin up a provisional account so we can take the order
      // now and text them a link to finish sign-up.
      const prov = await createProvisionalAccount(phone);
      orgId = prov.orgId;
      requestedById = prov.userId;
      provisional = true;
    }
  } else {
    // No usable caller_id → demo fallback so a live call never hard-fails.
    orgId = await fallbackOrgId();
    requestedById = null;
  }

  if (!orgId) {
    return NextResponse.json(
      { error: "No organization available to receive the order" },
      { status: 409 },
    );
  }

  // ── 2. Create the VOICE order + "created" event ─────────────────────────────
  const order = await createOrder({
    orgId,
    requestedById,
    title,
    description: body.description ?? null,
    maxBudgetCents,
    intakeChannel: "VOICE",
  });

  if (currency !== "EUR") {
    await prisma.order
      .update({ where: { id: order.id }, data: { currency } })
      .catch(() => {});
  }

  await appendOrderEvent({
    orderId: order.id,
    orgId,
    type: "note",
    actorType: requestedById ? "user" : "system",
    actorUserId: requestedById,
    message: provisional
      ? `Inbound voice order from a new caller ${formatPhoneDisplay(phone) || "(no number)"} — texting a sign-up link`
      : requestedById
        ? `Inbound voice order from ${formatPhoneDisplay(phone) || "a known caller"}`
        : `Inbound voice order — caller ${formatPhoneDisplay(phone) || "(no number)"}`,
    data: { callerPhone: phone, provisional, attributed: requestedById != null, currency },
  }).catch(() => {});

  // ── 3. Launch it now (the order runs immediately, even for new callers) ─────
  let status: string = order.status;
  try {
    const launched = await launchOrder({
      id: order.id,
      orgId,
      title: order.title,
      description: order.description,
    });
    status = launched.status;
  } catch (err) {
    console.warn("[voice/intake] launchOrder failed (ignored):", err);
  }

  // ── 4. Provisional caller → text them a claim link to finish sign-up ────────
  let claimSent = false;
  if (provisional && phone && requestedById) {
    try {
      const url = await issueClaimLink({
        phone,
        userId: requestedById,
        orgId,
        orderId: order.id,
      });
      const sms = await sendSms(
        phone,
        `Your sivra order "${title}" is on its way. Finish setting up your account to track it & get updates: ${url}`,
      );
      claimSent = sms.ok;
      await appendOrderEvent({
        orderId: order.id,
        orgId,
        type: "note",
        actorType: "system",
        message: claimSent
          ? "Sent a sign-up link by SMS to the caller."
          : "Could not send the sign-up SMS (will still appear once they sign up).",
      }).catch(() => {});
    } catch (err) {
      console.warn("[voice/intake] claim SMS failed (ignored):", err);
    }
  }

  return NextResponse.json(
    { orderId: order.id, status, provisional, claimSent },
    { status: 201 },
  );
}

interface VerifiedCaller {
  userId: string;
  orgId: string;
  isProvisional: boolean;
}

/**
 * Match a normalized E.164 number to a VERIFIED account (real or provisional)
 * and return their primary (oldest) org. Only verified phones match — an
 * unconfirmed number on someone's profile never silently captures a call.
 */
async function resolveVerifiedCaller(phoneE164: string): Promise<VerifiedCaller | null> {
  const user = await prisma.user.findFirst({
    where: { phone: phoneE164, phoneVerifiedAt: { not: null } },
    select: {
      id: true,
      isProvisional: true,
      memberships: { orderBy: { createdAt: "asc" }, take: 1, select: { orgId: true } },
    },
  });
  const orgId = user?.memberships[0]?.orgId;
  if (!user || !orgId) return null;
  return { userId: user.id, orgId, isProvisional: user.isProvisional };
}

/** Demo fallback org for a call with no usable caller_id. */
async function fallbackOrgId(): Promise<string | null> {
  const configured = process.env.DEFAULT_VOICE_ORG_ID?.trim();
  if (configured) {
    const exists = await prisma.organization.findUnique({
      where: { id: configured },
      select: { id: true },
    });
    if (exists) return exists.id;
  }
  const first = await prisma.organization.findFirst({
    orderBy: { createdAt: "asc" },
    select: { id: true },
  });
  return first?.id ?? null;
}
