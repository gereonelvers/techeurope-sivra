import Link from "next/link";
import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/db";
import { ORG_COOKIE } from "@/lib/org";
import { Wordmark } from "@/app/_components/Wordmark";

// Public page (NOT under /app, so not behind the session middleware). Accepts an
// org invitation: if the visitor isn't signed in we bounce them to /signin with
// a callbackUrl back here; once signed in they accept → Membership created,
// invite marked acceptedAt, active org cookie set, redirect to /app.

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <Link href="/" aria-label="sivra home" className="mb-10 inline-block">
        <Wordmark className="h-8" />
      </Link>
      {children}
    </main>
  );
}

export default async function InvitePage({
  params,
}: {
  params: { token: string };
}) {
  const invite = await prisma.invite.findUnique({
    where: { token: params.token },
    include: { org: { select: { id: true, name: true } } },
  });

  if (!invite) {
    return (
      <Shell>
        <h1 className="text-3xl font-semibold">Invitation not found</h1>
        <p className="mt-2 text-sm leading-relaxed text-ink/65">
          This invitation link is invalid or has been revoked.
        </p>
        <p className="mt-8 text-sm text-ink/50">
          <Link href="/" className="hover:text-accent">
            ← Back home
          </Link>
        </p>
      </Shell>
    );
  }

  const expired = invite.expiresAt.getTime() < Date.now();
  const alreadyAccepted = Boolean(invite.acceptedAt);

  if (expired || alreadyAccepted) {
    return (
      <Shell>
        <h1 className="text-3xl font-semibold">
          {alreadyAccepted ? "Already accepted" : "Invitation expired"}
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-ink/65">
          {alreadyAccepted
            ? `This invitation to ${invite.org.name} has already been accepted.`
            : `This invitation to ${invite.org.name} has expired. Ask an admin to send a new one.`}
        </p>
        <p className="mt-8 text-sm text-ink/50">
          <Link href="/app" className="hover:text-accent">
            Go to dashboard →
          </Link>
        </p>
      </Shell>
    );
  }

  const session = await auth();

  // Not signed in → send to magic-link, returning here afterwards.
  if (!session?.user?.id) {
    redirect(`/signin?callbackUrl=/invite/${params.token}`);
  }

  // Server action: accept the invite for the signed-in user.
  async function acceptInvite() {
    "use server";
    const s = await auth();
    const userId = s?.user?.id;
    if (!userId) {
      redirect(`/signin?callbackUrl=/invite/${params.token}`);
    }

    // Re-read to avoid a stale/raced invite.
    const fresh = await prisma.invite.findUnique({
      where: { token: params.token },
    });
    if (!fresh || fresh.acceptedAt || fresh.expiresAt.getTime() < Date.now()) {
      redirect("/app");
    }

    // Idempotent: upsert the membership (no-op if it already exists).
    await prisma.membership.upsert({
      where: { orgId_userId: { orgId: fresh.orgId, userId: userId! } },
      update: {},
      create: {
        orgId: fresh.orgId,
        userId: userId!,
        role: fresh.role,
        purchasingRole: fresh.purchasingRole,
      },
    });
    await prisma.invite.update({
      where: { id: fresh.id },
      data: { acceptedAt: new Date() },
    });

    // Make the joined org active.
    cookies().set(ORG_COOKIE, fresh.orgId, {
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      maxAge: 60 * 60 * 24 * 365,
    });
    redirect("/app");
  }

  return (
    <Shell>
      <p className="mb-3 text-sm font-medium uppercase tracking-[0.18em] text-accent">
        You're invited
      </p>
      <h1 className="text-3xl font-semibold">Join {invite.org.name}</h1>
      <p className="mt-2 text-sm leading-relaxed text-ink/65">
        You'll join as <b>{invite.role.toLowerCase()}</b>
        {invite.purchasingRole ? (
          <>
            {" "}
            with the purchasing role{" "}
            <b>{invite.purchasingRole.replace(/_/g, " ")}</b>
          </>
        ) : null}
        . Signed in as {session.user.email}.
      </p>

      <form action={acceptInvite} className="mt-8">
        <button type="submit" className="btn-accent w-full">
          Accept invitation
        </button>
      </form>

      <p className="mt-8 text-sm text-ink/50">
        <Link href="/app" className="hover:text-accent">
          Not now → dashboard
        </Link>
      </p>
    </Shell>
  );
}
