"use client";

import Link from "next/link";
import { useEffect } from "react";

// Route-level error boundary for the order detail page. A transient render
// error during live polling no longer blanks the page with "Application error"
// — the order itself is safe; this is just the live view, so offer a retry.
export default function OrderDetailError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[order detail] render error:", error);
  }, [error]);

  return (
    <div>
      <Link href="/app/orders" className="text-sm text-accent hover:opacity-80">
        ← Orders
      </Link>
      <div className="mt-6 rounded-xl border border-amber-500/25 bg-amber-50/60 p-5">
        <p className="text-sm font-semibold text-amber-900">
          The live order view hit a snag while updating.
        </p>
        <p className="mt-1 text-sm text-ink/60">
          The order itself is fine — this is just the live display refreshing. Reload it.
        </p>
        <button type="button" onClick={() => reset()} className="btn-accent mt-4">
          Reload this order
        </button>
      </div>
    </div>
  );
}
