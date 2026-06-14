import type { Metadata } from "next";
import { auth } from "@/lib/auth";
import { SiteHeader } from "./_components/landing/SiteHeader";
import { Hero } from "./_components/landing/Hero";
import { ValueCards } from "./_components/landing/ValueCards";
import { LongTail } from "./_components/landing/LongTail";
import { FleetUSP } from "./_components/landing/FleetUSP";
import { RouterUSP } from "./_components/landing/RouterUSP";
import { HowItWorks } from "./_components/landing/HowItWorks";
import { ClosingCTA } from "./_components/landing/ClosingCTA";
import { CallSivraFab } from "./_components/landing/CallSivraFab";

export const metadata: Metadata = {
  title: "sivra — tail-spend procurement, handled",
  description:
    "Strategic-procurement tools optimize the spend you've already structured. sivra handles the rest — tail spend, one-off buys, new-supplier discovery — with a fleet of vision agents that shops the open market and a router that learns who really approves.",
};

export default async function LandingPage() {
  const session = await auth();
  const signedIn = Boolean(session?.user);

  return (
    <main className="min-h-screen">
      <SiteHeader signedIn={signedIn} />
      <Hero />
      <ValueCards />
      <LongTail />
      <FleetUSP />
      <RouterUSP />
      <HowItWorks />
      <ClosingCTA signedIn={signedIn} />
      <CallSivraFab />
    </main>
  );
}
