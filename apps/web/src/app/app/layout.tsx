import { signOut } from "@/lib/auth";
import { prisma } from "@/lib/db";
import {
  requireSession,
  listMemberships,
  activeOrg,
  canManageOrg,
} from "@/lib/org";
import { AppShell } from "./_components/AppShell";
import { CreateFirstOrg } from "./_components/CreateFirstOrg";
import { AddPhone } from "./_components/AddPhone";
import { Wordmark } from "@/app/_components/Wordmark";

// Persistent app shell for /app/*. Guards via requireSession() (middleware does
// a cheap cookie check at the edge; this is the real server-side gate). Renders
// the sidebar + org switcher; children render the page body. The active org is
// derived from the `sivra_org` cookie via activeOrg().
export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await requireSession();
  const memberships = await listMemberships(session);
  const active = await activeOrg(session);
  const me = await prisma.user.findUnique({
    where: { id: session.user!.id! },
    select: { phoneVerifiedAt: true, isProvisional: true },
  });

  async function doSignOut() {
    "use server";
    await signOut({ redirectTo: "/" });
  }

  // Focused onboarding screen wrapper (sivra wordmark + sign-out).
  function OnboardingShell({ children }: { children: React.ReactNode }) {
    return (
      <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
        <Wordmark className="mb-10 h-8" />
        {children}
        <form action={doSignOut} className="mt-8">
          <button type="submit" className="text-sm text-ink/50 hover:text-accent">
            Sign out
          </button>
        </form>
      </div>
    );
  }

  // No org yet → focused create-your-first-org screen (still authed).
  if (!active) {
    return (
      <OnboardingShell>
        <CreateFirstOrg />
      </OnboardingShell>
    );
  }

  // Org exists but no verified phone (website sign-up) → required add-phone step.
  // Provisional accounts already have a confirmed phone, so they skip this.
  if (!me?.phoneVerifiedAt && !me?.isProvisional) {
    return (
      <OnboardingShell>
        <AddPhone />
      </OnboardingShell>
    );
  }

  const orgs = memberships.map((m) => ({
    orgId: m.orgId,
    name: m.org.name,
    slug: m.org.slug,
  }));
  const canManage = canManageOrg(active.role);
  const roleLine = `${active.role}${
    active.purchasingRole ? ` · ${active.purchasingRole}` : ""
  }${!canManage ? " · view-only" : ""}`;

  return (
    <AppShell
      orgs={orgs}
      activeOrgId={active.orgId}
      canManage={canManage}
      userEmail={session.user.email ?? ""}
      roleLine={roleLine}
      signOut={doSignOut}
    >
      {children}
    </AppShell>
  );
}
