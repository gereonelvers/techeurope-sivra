import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Protects /app/* at the edge. We use DATABASE sessions, and the Auth.js Email
// provider pulls in nodemailer (not edge-runtime safe), so we do NOT import the
// full `auth` here. Instead we do a cheap presence check on the session cookie;
// the actual session is verified server-side in the /app pages via requireSession().
const SESSION_COOKIES = [
  "authjs.session-token",
  "__Secure-authjs.session-token",
  // legacy next-auth cookie names, just in case
  "next-auth.session-token",
  "__Secure-next-auth.session-token",
];

export function middleware(req: NextRequest) {
  const hasSession = SESSION_COOKIES.some((name) =>
    req.cookies.has(name),
  );

  if (!hasSession) {
    const signInUrl = new URL("/signin", req.url);
    signInUrl.searchParams.set("callbackUrl", req.nextUrl.pathname);
    return NextResponse.redirect(signInUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/app/:path*"],
};
