// Phone ↔ account linking. The SMS link we text someone IS the proof of phone
// ownership (only they receive it). Two flows:
//   CLAIM   — an unknown caller's order is parked in a provisional account; the
//             link opens /claim/:token to finish sign-up (email + org name).
//   CONFIRM — a signed-in user added a phone on the website; the link confirms
//             it and sets User.phone + phoneVerifiedAt.
//
// Phone strings are ALWAYS normalized to E.164 (lib/phone) before they reach
// here, so matching is format-proof.

import { randomBytes } from "crypto";
import { prisma } from "@/lib/db";
import { createOrgForUser } from "@/lib/org";
import { phoneDigits } from "@/lib/phone";

const CLAIM_TTL_MS = 1000 * 60 * 60 * 24 * 14; // 14 days to finish sign-up
const CONFIRM_TTL_MS = 1000 * 60 * 30; // 30 min to click the confirm link

/** Absolute base URL for links we put in SMS (must be publicly reachable). */
export function appBaseUrl(): string {
  return (process.env.APP_URL || process.env.AUTH_URL || "https://sivra.io").replace(
    /\/+$/,
    "",
  );
}

function newToken(): string {
  return randomBytes(24).toString("hex");
}

function normalizeEmail(raw: string | null | undefined): string | null {
  const e = String(raw ?? "").trim().toLowerCase();
  // minimal sanity; the magic-link send is the real validator
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e) ? e : null;
}

/** Oldest membership's org for a user (their "primary" org). */
export async function primaryOrgId(userId: string): Promise<string | null> {
  const m = await prisma.membership.findFirst({
    where: { userId },
    orderBy: { createdAt: "asc" },
    select: { orgId: true },
  });
  return m?.orgId ?? null;
}

/**
 * Provisional account for an unknown caller: a User whose phone is already
 * confirmed (the inbound call proves they hold it) + their own Org. The email is
 * a unique placeholder until they claim it. Returns the new userId + orgId.
 */
export async function createProvisionalAccount(
  phoneE164: string,
): Promise<{ userId: string; orgId: string }> {
  const placeholderEmail = `pending+${phoneDigits(phoneE164)}@phone.sivra.invalid`;
  const user = await prisma.user.create({
    data: {
      email: placeholderEmail,
      phone: phoneE164,
      phoneVerifiedAt: new Date(), // the call is proof of ownership
      isProvisional: true,
    },
    select: { id: true },
  });
  const org = await createOrgForUser(user.id, "Personal workspace");
  return { userId: user.id, orgId: org.id };
}

/** Create a CLAIM token for a provisional order and return the absolute link. */
export async function issueClaimLink(opts: {
  phone: string;
  userId: string;
  orgId: string;
  orderId: string;
}): Promise<string> {
  const token = newToken();
  await prisma.phoneVerification.create({
    data: {
      token,
      phone: opts.phone,
      kind: "CLAIM",
      userId: opts.userId,
      orgId: opts.orgId,
      orderId: opts.orderId,
      expiresAt: new Date(Date.now() + CLAIM_TTL_MS),
    },
  });
  return `${appBaseUrl()}/claim/${token}`;
}

/** Create a CONFIRM token for a signed-in user adding a phone; return the link. */
export async function issueConfirmLink(opts: {
  phone: string;
  userId: string;
}): Promise<string> {
  const token = newToken();
  await prisma.phoneVerification.create({
    data: {
      token,
      phone: opts.phone,
      kind: "CONFIRM",
      userId: opts.userId,
      expiresAt: new Date(Date.now() + CONFIRM_TTL_MS),
    },
  });
  return `${appBaseUrl()}/phone/confirm/${token}`;
}

/** Confirm a CONFIRM token → set the user's verified phone. Idempotent: a
 *  refresh of an already-used link that linked this very number is a success. */
export async function confirmPhone(
  token: string,
): Promise<{ ok: boolean; error?: string }> {
  const v = await prisma.phoneVerification.findUnique({ where: { token } });
  if (!v || v.kind !== "CONFIRM" || !v.userId) {
    return { ok: false, error: "This confirmation link is invalid." };
  }
  if (v.consumedAt) {
    // Already used — if it resulted in this user holding this verified number,
    // treat a re-open of the link as success (don't scare them with an error).
    const u = await prisma.user.findUnique({
      where: { id: v.userId },
      select: { phone: true, phoneVerifiedAt: true },
    });
    if (u?.phone === v.phone && u.phoneVerifiedAt) return { ok: true };
    return { ok: false, error: "This confirmation link has already been used." };
  }
  if (v.expiresAt < new Date()) {
    return { ok: false, error: "This confirmation link has expired." };
  }
  // Guard against the number being claimed by someone else since we issued it.
  const taken = await prisma.user.findFirst({
    where: { phone: v.phone, NOT: { id: v.userId } },
    select: { id: true },
  });
  if (taken) {
    return { ok: false, error: "That number is already linked to another account." };
  }
  await prisma.user.update({
    where: { id: v.userId },
    data: { phone: v.phone, phoneVerifiedAt: new Date() },
  });
  await prisma.phoneVerification.update({
    where: { token },
    data: { consumedAt: new Date() },
  });
  return { ok: true };
}

/**
 * Finalize a CLAIM: turn the provisional account into a real one (email + org
 * name), OR — if that email already has an account — move the order into that
 * account and discard the provisional shell. Returns the email to sign in with.
 */
export async function claimAccount(
  token: string,
  rawEmail: string,
  rawOrgName: string,
): Promise<{ ok: boolean; email?: string; error?: string }> {
  const email = normalizeEmail(rawEmail);
  if (!email) return { ok: false, error: "Please enter a valid email address." };
  const orgName = String(rawOrgName ?? "").trim();

  const v = await prisma.phoneVerification.findUnique({ where: { token } });
  if (!v || v.kind !== "CLAIM" || v.consumedAt || v.expiresAt < new Date()) {
    return { ok: false, error: "This link is invalid or has expired." };
  }
  const prov = v.userId
    ? await prisma.user.findUnique({ where: { id: v.userId } })
    : null;
  if (!prov || !prov.isProvisional) {
    return { ok: false, error: "This order has already been set up." };
  }

  const existing = await prisma.user.findUnique({ where: { email } });

  if (existing && existing.id !== prov.id) {
    // ── MERGE into the existing account ──────────────────────────────────────
    const targetOrgId = await primaryOrgId(existing.id);
    if (!targetOrgId) {
      return {
        ok: false,
        error: "That email has an account but no workspace yet — sign in first, then call again.",
      };
    }
    await prisma.$transaction(async (tx) => {
      if (v.orderId) {
        await tx.order.update({
          where: { id: v.orderId },
          data: { orgId: targetOrgId, requestedById: existing.id },
        });
        await tx.orderEvent.updateMany({
          where: { orderId: v.orderId },
          data: { orgId: targetOrgId },
        });
        await tx.escalation.updateMany({
          where: { orderId: v.orderId },
          data: { orgId: targetOrgId },
        });
      }
      // Link the phone to the existing account if it has none.
      if (!existing.phone) {
        await tx.user.update({
          where: { id: existing.id },
          data: { phone: prov.phone, phoneVerifiedAt: new Date() },
        });
      }
      await tx.phoneVerification.update({
        where: { token },
        data: { consumedAt: new Date() },
      });
      // Drop the provisional shell. Order/events were moved out first, so the
      // org-cascade only removes the empty membership + policy.
      if (v.orgId) await tx.organization.delete({ where: { id: v.orgId } });
      await tx.user.delete({ where: { id: prov.id } });
    });
    return { ok: true, email };
  }

  // ── NEW account: claim the provisional user + name their workspace ─────────
  await prisma.$transaction(async (tx) => {
    await tx.user.update({
      where: { id: prov.id },
      data: { email, isProvisional: false },
    });
    if (v.orgId && orgName) {
      await tx.organization.update({ where: { id: v.orgId }, data: { name: orgName } });
    }
    await tx.phoneVerification.update({
      where: { token },
      data: { consumedAt: new Date() },
    });
  });
  return { ok: true, email };
}
