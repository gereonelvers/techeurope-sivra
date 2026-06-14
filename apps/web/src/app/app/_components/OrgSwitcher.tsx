"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

export interface OrgOption {
  orgId: string;
  name: string;
  slug: string;
}

// Client org switcher: persists the active org via POST /api/orgs/switch (which
// sets the `sivra_org` cookie) and refreshes server components so every page
// re-derives its orgId from the new active org.
export function OrgSwitcher({
  orgs,
  activeOrgId,
}: {
  orgs: OrgOption[];
  activeOrgId: string;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [value, setValue] = useState(activeOrgId);

  async function onChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const orgId = e.target.value;
    if (orgId === "__new__") {
      router.push("/app/settings?new=1");
      return;
    }
    setValue(orgId);
    const res = await fetch("/api/orgs/switch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ orgId }),
    });
    if (res.ok) {
      startTransition(() => router.refresh());
    } else {
      setValue(activeOrgId); // revert on failure
    }
  }

  return (
    <div className="relative">
      <label className="mb-1.5 block text-[11px] font-medium uppercase tracking-[0.14em] text-ink/45">
        Organization
      </label>
      <select
        value={value}
        onChange={onChange}
        disabled={pending}
        className="field cursor-pointer appearance-none pr-9 text-sm font-medium"
      >
        {orgs.map((o) => (
          <option key={o.orgId} value={o.orgId}>
            {o.name}
          </option>
        ))}
        <option value="__new__">+ New organization…</option>
      </select>
      <span className="pointer-events-none absolute bottom-3.5 right-3 text-ink/40">
        ▾
      </span>
    </div>
  );
}
