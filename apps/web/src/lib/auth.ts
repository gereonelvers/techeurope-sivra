import NextAuth from "next-auth";
import type { NextAuthConfig } from "next-auth";
import { PrismaAdapter } from "@auth/prisma-adapter";
import { prisma } from "@/lib/db";
import { sendEmail } from "@/lib/brevo";

// ─────────────────────────────────────────────────────────────────────────────
// Auth.js v5 — passwordless magic-link sign-in delivered by Brevo, backed by
// Prisma with DATABASE sessions (not JWT). The Email provider stores a
// VerificationToken via the adapter; we only override how the link is delivered.
//
// Feature agents: import { auth } to read the session in server components /
// route handlers / middleware. Use { signIn, signOut } for the sign-in form
// and sign-out actions. handlers (GET/POST) are mounted at
// src/app/api/auth/[...nextauth]/route.ts.
// ─────────────────────────────────────────────────────────────────────────────

function magicLinkEmail(url: string, host: string) {
  const subject = `Sign in to sivra`;
  const html = `
  <div style="background:#F4F2EB;padding:40px 0;font-family:Inter,system-ui,-apple-system,sans-serif;color:#211f1a;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
      <tr><td align="center">
        <table role="presentation" width="480" cellpadding="0" cellspacing="0"
          style="background:#ffffff;border:1px solid #e6e2d6;border-radius:14px;padding:36px;">
          <tr><td>
            <img src="https://sivra.io/sivra-wordmark.png" alt="sivra" width="104" style="display:block;height:auto;margin:0 0 12px;" />
            <p style="font-size:15px;line-height:1.6;margin:0 0 24px;color:#4a463f;">
              Click the button below to sign in to <b>${host}</b>. This link
              expires in 24 hours and can only be used once.
            </p>
            <a href="${url}"
              style="display:inline-block;background:#3A357C;color:#ffffff;text-decoration:none;
                     padding:13px 28px;border-radius:10px;font-size:15px;font-weight:600;">
              Sign in to sivra
            </a>
            <p style="font-size:13px;line-height:1.6;margin:28px 0 0;color:#8a857a;">
              If you didn't request this, you can safely ignore this email.
            </p>
          </td></tr>
        </table>
      </td></tr>
    </table>
  </div>`;
  const text = `Sign in to sivra (${host})\n\n${url}\n\nThis link expires in 24 hours. If you didn't request it, ignore this email.`;
  return { subject, html, text };
}

export const authConfig = {
  adapter: PrismaAdapter(prisma),
  session: { strategy: "database" },
  secret: process.env.AUTH_SECRET,
  pages: {
    signIn: "/signin",
    verifyRequest: "/signin?check=1",
  },
  providers: [
    {
      id: "email",
      type: "email",
      name: "Email",
      // 24h magic-link TTL; from address comes from Brevo sender env.
      maxAge: 24 * 60 * 60,
      from: process.env.BREVO_SENDER_EMAIL ?? "no-reply@sivra.io",
      // These server-only fields satisfy the EmailConfig type; delivery is
      // fully handled by sendVerificationRequest below (Brevo, not SMTP).
      server: {},
      options: {},
      async sendVerificationRequest({
        identifier,
        url,
      }: {
        identifier: string;
        url: string;
      }) {
        const host = new URL(url).host;
        const { subject, html, text } = magicLinkEmail(url, host);
        await sendEmail({ to: identifier, subject, html, text });
      },
    },
  ],
} satisfies NextAuthConfig;

export const { handlers, auth, signIn, signOut } = NextAuth(authConfig);
