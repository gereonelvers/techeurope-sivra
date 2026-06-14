import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { requireSession, UnauthorizedError } from "@/lib/org";
import { normalizePhoneE164 } from "@/lib/phone";
import { issueConfirmLink } from "@/lib/phone-link";
import { sendSms } from "@/lib/dispatch";

// POST /api/phone/start — a signed-in user adds (or changes) their phone. We
// normalize it, make sure it isn't already linked elsewhere, and TEXT a confirm
// link. Clicking that link (proof of possession) finishes the link-up.
// Body: { phone }.
export async function POST(req: NextRequest) {
  try {
    const session = await requireSession();
    const userId = session.user!.id!;
    const body = (await req.json().catch(() => ({}))) as { phone?: string };
    const phone = normalizePhoneE164(body.phone);
    if (!phone) {
      return NextResponse.json(
        { error: "Please enter a valid phone number." },
        { status: 400 },
      );
    }

    // Taken by someone else (verified)?
    const taken = await prisma.user.findFirst({
      where: { phone, phoneVerifiedAt: { not: null }, NOT: { id: userId } },
      select: { id: true },
    });
    if (taken) {
      return NextResponse.json(
        { error: "That number is already linked to another account." },
        { status: 409 },
      );
    }

    // Already my verified number → nothing to do.
    const me = await prisma.user.findUnique({
      where: { id: userId },
      select: { phone: true, phoneVerifiedAt: true },
    });
    if (me?.phone === phone && me.phoneVerifiedAt) {
      return NextResponse.json({ ok: true, alreadyVerified: true });
    }

    const url = await issueConfirmLink({ phone, userId });
    const sms = await sendSms(
      phone,
      `Confirm this number for your sivra account: ${url}`,
    );
    if (!sms.ok) {
      return NextResponse.json(
        { error: "Couldn't send the SMS — double-check the number and try again." },
        { status: 502 },
      );
    }
    return NextResponse.json({ ok: true, sent: true });
  } catch (err) {
    if (err instanceof UnauthorizedError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }
}
