"use client";

import { useEffect, useState } from "react";

// Renders a timestamp as LOCAL time, but only AFTER mount. The server and the
// initial client render both show a neutral placeholder, so they agree — which
// avoids the React hydration mismatch (#418/#425) that `toLocale*String()`
// causes (server formats in the server's tz/locale, the browser in the user's).
// The local time fills in after hydration via the effect.
export function LocalDateTime({
  iso,
  dateOnly = false,
}: {
  iso: string;
  dateOnly?: boolean;
}) {
  const [text, setText] = useState("");
  useEffect(() => {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return;
    setText(dateOnly ? d.toLocaleDateString() : d.toLocaleString());
  }, [iso, dateOnly]);
  return <span suppressHydrationWarning>{text || "—"}</span>;
}
