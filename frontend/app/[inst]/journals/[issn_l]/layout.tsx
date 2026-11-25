import type { Metadata } from "next";

import { Seed } from "@/components/seed";
import type { JournalDetailResponse } from "@/lib/api";
import { docPage, pageContext } from "@/lib/page-meta";
import { qk } from "@/lib/query-keys";
import { fetchForRender } from "@/lib/server-fetch";

type JournalRoute = { params: Promise<{ inst: string; issn_l: string }> };

/** The journal document the page reads before a funder or year lens is set. */
function loadJournal(inst: string, issnL: string) {
  return fetchForRender<JournalDetailResponse>({
    path: `/api/v1/${inst}/journals/${issnL}`,
    query: { include_gaps: "false" },
  });
}

export async function generateMetadata({ params }: JournalRoute): Promise<Metadata> {
  const { inst, issn_l } = await params;
  const issnL = decodeURIComponent(issn_l);
  const [{ t, short }, doc] = await Promise.all([
    pageContext(inst, "journals"),
    loadJournal(inst, issnL),
  ]);
  const title = doc?.journal?.title ?? undefined;
  return docPage(inst, `/journals/${encodeURIComponent(issnL)}`, {
    title,
    description: title ? t("meta.description", { title, inst: short }) : undefined,
  });
}

/** Seeds the cache, so the page renders its content on the server. */
export default async function JournalLayout({
  children,
  params,
}: JournalRoute & { children: React.ReactNode }) {
  const { inst, issn_l } = await params;
  const issnL = decodeURIComponent(issn_l);
  return (
    <Seed queryKey={qk.journal(inst, issnL)} data={await loadJournal(inst, issnL)}>
      {children}
    </Seed>
  );
}
