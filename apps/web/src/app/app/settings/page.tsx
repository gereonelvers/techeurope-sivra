import { requireSession, activeOrg, canManageOrg } from "@/lib/org";
import { prisma } from "@/lib/db";
import { normalizeFleetTier } from "@/lib/fleet-tiers";
import { formatPhoneDisplay } from "@/lib/phone";
import { OrgSettings } from "./OrgSettings";
import { PhoneSettings } from "./PhoneSettings";

// Settings page: rename the active org (OWNER/ADMIN), set the default browsing-
// fleet size, and create a new org. ?new=1 (from the org switcher's "+ New
// organization") opens the create form.
export default async function SettingsPage({
  searchParams,
}: {
  searchParams: { new?: string };
}) {
  const session = await requireSession();
  const active = await activeOrg(session);
  if (!active) return null;

  const canManage = canManageOrg(active.role);

  // activeOrg only selects id/name/slug — fetch the fleet default directly.
  const orgRow = await prisma.organization.findUnique({
    where: { id: active.orgId },
    select: { defaultFleetTier: true },
  });
  const defaultFleetTier = normalizeFleetTier(orgRow?.defaultFleetTier);

  // Personal: the phone linked to THIS user (not the org).
  const me = await prisma.user.findUnique({
    where: { id: session.user!.id! },
    select: { phone: true, phoneVerifiedAt: true },
  });
  const phoneDisplay =
    me?.phone && me.phoneVerifiedAt ? formatPhoneDisplay(me.phone) : null;

  return (
    <div>
      <header className="border-b border-ink/10 pb-6">
        <h1 className="text-3xl font-semibold">Settings</h1>
        <p className="mt-2 text-sm text-ink/60">
          Manage {active.org.name} or spin up a new organization.
        </p>
      </header>

      <div className="mt-8 space-y-8">
        <PhoneSettings currentPhoneDisplay={phoneDisplay} />
      </div>

      <OrgSettings
        orgId={active.orgId}
        orgName={active.org.name}
        orgSlug={active.org.slug}
        defaultFleetTier={defaultFleetTier}
        canManage={canManage}
        startCreating={searchParams.new === "1"}
      />
    </div>
  );
}
