import Link from "next/link";
import { Wordmark } from "../Wordmark";

/**
 * Sticky landing header. `session` is resolved server-side in page.tsx and
 * passed as a plain boolean so this stays a server component.
 */
export function SiteHeader({ signedIn }: { signedIn: boolean }) {
  return (
    <header className="sticky top-0 z-30 border-b border-ink/10 bg-paper/80 backdrop-blur-md">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
        <Link href="/" aria-label="sivra home">
          <Wordmark className="h-7" />
        </Link>
        <nav className="flex items-center gap-7 text-sm">
          <a
            href="#fleet"
            className="hidden text-ink/60 transition-colors hover:text-ink sm:inline"
          >
            The fleet
          </a>
          <a
            href="#router"
            className="hidden text-ink/60 transition-colors hover:text-ink sm:inline"
          >
            The router
          </a>
          <a
            href="#how"
            className="hidden text-ink/60 transition-colors hover:text-ink sm:inline"
          >
            Under the hood
          </a>
          {signedIn ? (
            <Link
              href="/app"
              className="font-medium text-accent hover:opacity-80"
            >
              Dashboard &rarr;
            </Link>
          ) : (
            <Link
              href="/signin"
              className="font-medium text-accent hover:opacity-80"
            >
              Sign in
            </Link>
          )}
        </nav>
      </div>
    </header>
  );
}
