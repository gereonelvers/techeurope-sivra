// The sivra brand wordmark (circle long-tail mark + "SIVRA"). Replaces the old
// text wordmark everywhere — headers, auth/claim/confirm screens. Plain <img> so
// it drops into both server and client trees; size it via className (defaults to
// a header-friendly height).
export function Wordmark({ className = "" }: { className?: string }) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src="/sivra-wordmark.png"
      alt="sivra"
      className={`h-7 w-auto ${className}`.trim()}
    />
  );
}
