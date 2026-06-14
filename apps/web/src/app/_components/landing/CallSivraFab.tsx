/**
 * CallSivraFab — mobile-only floating "Call Sivra" action button.
 *
 * Her photo as a circular avatar (≈60px) fixed to the bottom-right corner,
 * with a small "Call Sivra" pill beside it. Mobile-only (`lg:hidden`); on
 * desktop the closing CTA carries the photo + phone treatment instead.
 */
export function CallSivraFab() {
  return (
    <a
      href="tel:+14472154920"
      aria-label="Call Sivra — +1 447 215 4920"
      className="group fixed bottom-4 right-4 z-40 flex items-center gap-2.5 lg:hidden"
    >
      <span className="rounded-full bg-ink/90 px-3 py-1.5 text-xs font-semibold text-paper shadow-lg backdrop-blur-sm">
        Call Sivra
      </span>
      <span className="relative inline-flex">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/sivra-person.png"
          alt="Sivra, your procurement employee"
          className="size-14 rounded-full object-cover shadow-xl ring-2 ring-accent transition group-active:scale-95"
          style={{ objectPosition: "50% 22%" }}
        />
        {/* phone badge */}
        <span
          aria-hidden
          className="absolute -bottom-0.5 -right-0.5 flex size-6 items-center justify-center rounded-full bg-accent text-paper shadow-md ring-2 ring-paper"
        >
          <svg viewBox="0 0 24 24" className="size-3" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.9.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z" />
          </svg>
        </span>
      </span>
    </a>
  );
}
