import { notFound } from "next/navigation";
import { getSkin } from "@/lib/skins";
import { getCart, getEpisodeId } from "@/lib/session";
import { isSite, Site } from "@/lib/types";
import { prisma } from "@/lib/db";
import { fromJson } from "@/lib/json";
import { Header } from "@/components/Header";
import { TaskBanner } from "@/components/TaskBanner";

export const dynamic = "force-dynamic";

// Per-skin shell: validates the site param, applies the skin background, and
// renders the header + (optional) active-task banner for agent visibility.
export default async function SiteLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: { site: string };
}) {
  if (!isSite(params.site)) {
    notFound();
  }
  const site = params.site as Site;
  const skin = getSkin(site);
  const cartCount = getCart(site).length;

  // Surface the current episode's task (if any) so an agent / human can see the
  // goal. Read-only; does not emit events.
  const episodeId = getEpisodeId();
  let task: { taskSpec: unknown; targetItemId: number | null } | null = null;
  if (episodeId) {
    const episode = await prisma.episode.findUnique({
      where: { id: episodeId },
      select: { taskSpec: true, targetItemId: true, site: true },
    });
    if (episode && episode.site === site) {
      task = {
        taskSpec: fromJson(episode.taskSpec),
        targetItemId: episode.targetItemId,
      };
    }
  }

  return (
    <div className={`min-h-screen ${skin.theme.appBg} ${skin.theme.bodyText}`}>
      <Header skin={skin} site={site} q="" cartCount={cartCount} />
      {task ? <TaskBanner skin={skin} task={task} /> : null}
      <main className="mx-auto max-w-6xl px-4 py-5">{children}</main>
    </div>
  );
}
