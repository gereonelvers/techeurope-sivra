"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { NavLinks } from "./NavLinks";
import { OrgSwitcher, type OrgOption } from "./OrgSwitcher";
import { Wordmark } from "@/app/_components/Wordmark";

// Interactive app shell. The layout (server component) does all the
// session/org/prisma work and passes plain data + a server-action sign-out down
// here. On lg+ we render the original fixed w-64 sidebar untouched; on small
// screens that sidebar becomes a slide-in drawer toggled from a slim top bar.
export function AppShell({
  orgs,
  activeOrgId,
  canManage,
  userEmail,
  roleLine,
  signOut,
  children,
}: {
  orgs: OrgOption[];
  activeOrgId: string;
  canManage: boolean;
  userEmail: string;
  roleLine: string;
  // Server action threaded through from the layout, used as a <form action>.
  signOut: () => Promise<void>;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  // Close the drawer whenever the route changes (nav-link tap).
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  // Lock body scroll while the drawer is open; close on Escape.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // The sidebar body — shared between the fixed lg sidebar and the mobile drawer.
  const sidebarBody = (
    <>
      <Link href="/app" className="mb-7 inline-block" aria-label="sivra home">
        <Wordmark className="h-7" />
      </Link>

      <OrgSwitcher orgs={orgs} activeOrgId={activeOrgId} />

      <div className="mt-7 flex-1">
        <NavLinks canManage={canManage} />
      </div>

      <div className="mt-6 border-t border-ink/10 pt-5">
        <p className="truncate text-sm font-medium">{userEmail}</p>
        <p className="mt-0.5 text-xs text-ink/55">{roleLine}</p>
        <form action={signOut} className="mt-3">
          <button
            type="submit"
            className="text-sm font-medium text-accent hover:opacity-80"
          >
            Sign out
          </button>
        </form>
      </div>
    </>
  );

  return (
    <div className="flex min-h-screen">
      {/* Desktop sidebar — unchanged at lg+; hidden on small screens. */}
      <aside className="hidden w-64 flex-col border-r border-ink/10 bg-white/40 px-5 py-7 lg:flex">
        {sidebarBody}
      </aside>

      {/* Mobile slide-in drawer + scrim (lg:hidden). */}
      <div className="lg:hidden">
        {/* Scrim */}
        <div
          onClick={() => setOpen(false)}
          aria-hidden={!open}
          className={[
            "fixed inset-0 z-40 bg-ink/40 transition-opacity duration-200",
            open ? "opacity-100" : "pointer-events-none opacity-0",
          ].join(" ")}
        />
        {/* Drawer */}
        <aside
          className={[
            "fixed inset-y-0 left-0 z-50 flex w-72 max-w-[80%] flex-col border-r border-ink/10 bg-paper px-5 py-7 shadow-xl transition-transform duration-200 ease-out",
            open ? "translate-x-0" : "-translate-x-full",
          ].join(" ")}
          aria-hidden={!open}
        >
          {sidebarBody}
        </aside>
      </div>

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Slim mobile top bar (lg:hidden). */}
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-ink/10 bg-paper/90 px-4 py-3 backdrop-blur lg:hidden">
          <button
            type="button"
            onClick={() => setOpen(true)}
            aria-label="Open menu"
            aria-expanded={open}
            className="-ml-1 inline-flex size-9 items-center justify-center rounded-lg text-ink/70 transition hover:bg-ink/5"
          >
            <svg
              width="20"
              height="20"
              viewBox="0 0 20 20"
              fill="none"
              aria-hidden="true"
            >
              <path
                d="M3 5h14M3 10h14M3 15h14"
                stroke="currentColor"
                strokeWidth="1.75"
                strokeLinecap="round"
              />
            </svg>
          </button>
          <Link href="/app" aria-label="sivra home">
            <Wordmark className="h-6" />
          </Link>
        </header>

        {/* Page body */}
        <main className="flex-1 overflow-x-hidden">
          <div className="mx-auto max-w-4xl px-4 py-6 sm:px-8 sm:py-10">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
