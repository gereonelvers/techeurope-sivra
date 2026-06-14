import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { sendEmail } from "@/lib/brevo";
import {
  requireSession,
  activeOrg,
  assertCanManage,
  UnauthorizedError,
  ForbiddenError,
} from "@/lib/org";
import { PURCHASING_ROLES } from "@/lib/policy";

const ORG_ROLES = ["OWNER", "ADMIN", "MEMBER"] as const;
const INVITE_TTL_DAYS = 14;

function inviteEmail(orgName: string, acceptUrl: string) {
  const subject = `You've been invited to ${orgName} on sivra`;
  const html = `
  <div style="background:#F4F2EB;padding:40px 0;font-family:Inter,system-ui,-apple-system,sans-serif;color:#211f1a;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
      <tr><td align="center">
        <table role="presentation" width="480" cellpadding="0" cellspacing="0"
          style="background:#ffffff;border:1px solid #e6e2d6;border-radius:14px;padding:36px;">
          <tr><td>
            <img src="https://sivra.io/sivra-wordmark.png" alt="sivra" width="104" style="display:block;height:auto;margin:0 0 12px;" />
            <p style="font-size:15px;line-height:1.6;margin:0 0 24px;color:#4a463f;">
              You've been invited to join <b>${orgName}</b> on sivra. Click below
              to accept and start working with your team.
            </p>
            <a href="${acceptUrl}"
              style="display:inline-block;background:#3A357C;color:#ffffff;text-decoration:none;
                     padding:13px 28px;border-radius:10px;font-size:15px;font-weight:600;">
              Accept invitation
            </a>
            <p style="font-size:13px;line-height:1.6;margin:28px 0 0;color:#8a857a;">
              This invitation expires in ${INVITE_TTL_DAYS} days. If you weren't
              expecting it, you can ignore this email.
            </p>
          </td></tr>
        </table>
      </td></tr>
    </table>
  </div>`;
  const text = `You've been invited to join ${orgName} on sivra.\n\nAccept: ${acceptUrl}\n\nThis invitation expires in ${INVITE_TTL_DAYS} days.`;
  return { subject, html, text };
}

// POST /api/invites { orgId?, email, role?, purchasingRole? }
// Creates an Invite row and sends a Brevo email with the accept link.
// OWNER/ADMIN only.
export async function POST(req: NextRequest) {
  try {
    const body = (await req.json().catch(() => ({}))) as {
      orgId?: string;
      email?: string;
      role?: string;
      purchasingRole?: string | null;
    };

    // Resolve org: explicit orgId (membership-checked in assertCanManage) or active.
    let orgId = body.orgId?.trim();
    if (!orgId) {
      const session = await requireSession();
      const m = await activeOrg(session);
      if (!m) throw new ForbiddenError("No active organization");
      orgId = m.orgId;
    }

    const membership = await assertCanManage(orgId); // membership + RBAC

    const email = String(body.email ?? "").trim().toLowerCase();
    if (!email || !email.includes("@")) {
      return NextResponse.json({ error: "valid email required" }, { status: 400 });
    }

    const role = (ORG_ROLES as readonly string[]).includes(body.role ?? "")
      ? (body.role as (typeof ORG_ROLES)[number])
      : "MEMBER";

    const purchasingRole =
      body.purchasingRole &&
      (PURCHASING_ROLES as readonly string[]).includes(body.purchasingRole)
        ? body.purchasingRole
        : null;

    // Already a member?
    const existingUser = await prisma.user.findUnique({
      where: { email },
      select: { id: true },
    });
    if (existingUser) {
      const already = await prisma.membership.findUnique({
        where: { orgId_userId: { orgId, userId: existingUser.id } },
        select: { id: true },
      });
      if (already) {
        return NextResponse.json(
          { error: "Already a member of this organization" },
          { status: 409 },
        );
      }
    }

    const expiresAt = new Date(Date.now() + INVITE_TTL_DAYS * 24 * 60 * 60 * 1000);
    const invite = await prisma.invite.create({
      data: {
        orgId,
        email,
        role,
        purchasingRole,
        invitedById: membership.userId,
        expiresAt,
      },
      include: { org: { select: { name: true } } },
    });

    const base = process.env.AUTH_URL ?? "http://localhost:3000";
    const acceptUrl = `${base.replace(/\/$/, "")}/invite/${invite.token}`;

    // Send the invite email (best-effort: don't fail the API if email errors,
    // since the invite row + link already exist).
    let emailSent = false;
    try {
      const { subject, html, text } = inviteEmail(invite.org.name, acceptUrl);
      await sendEmail({ to: email, subject, html, text });
      emailSent = true;
    } catch (e) {
      console.error("invite email failed:", e);
    }

    return NextResponse.json(
      {
        invite: {
          id: invite.id,
          email: invite.email,
          role: invite.role,
          purchasingRole: invite.purchasingRole,
          expiresAt: invite.expiresAt,
        },
        acceptUrl,
        emailSent,
      },
      { status: 201 },
    );
  } catch (err) {
    if (err instanceof UnauthorizedError || err instanceof ForbiddenError) {
      return NextResponse.json({ error: err.message }, { status: err.status });
    }
    throw err;
  }
}
