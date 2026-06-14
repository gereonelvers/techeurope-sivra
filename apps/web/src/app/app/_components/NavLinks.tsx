"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

interface NavItem {
  href: string;
  label: string;
  exact?: boolean;
}

const NAV: NavItem[] = [
  { href: "/app", label: "Dashboard", exact: true },
  { href: "/app/orders", label: "Orders" },
  { href: "/app/team", label: "Team" },
  { href: "/app/policies", label: "Policies" },
  { href: "/app/settings", label: "Settings" },
];

// OWNER/ADMIN-only links (the global router controls live here).
const ADMIN_NAV: NavItem[] = [{ href: "/app/admin/router", label: "Router model" }];

// Sidebar nav with active-route highlighting. The Orders link points at the
// placeholder page owned by the orders agent. `canManage` (OWNER/ADMIN) reveals
// the admin section.
export function NavLinks({ canManage = false }: { canManage?: boolean }) {
  const pathname = usePathname();
  const items = canManage ? [...NAV, ...ADMIN_NAV] : NAV;

  return (
    <nav className="flex flex-col gap-0.5">
      {items.map((item) => {
        const active = item.exact
          ? pathname === item.href
          : pathname === item.href || pathname.startsWith(item.href + "/");
        return (
          <Link
            key={item.href}
            href={item.href}
            className={[
              "rounded-lg px-3 py-2 text-sm font-medium transition",
              active
                ? "bg-accent/10 text-accent"
                : "text-ink/70 hover:bg-ink/5 hover:text-ink",
            ].join(" ")}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
