import type { Metadata } from "next";

import { Seeds } from "@/components/seed";
import { SectionMessages } from "@/i18n/section-messages";
import type { JournalDetailResponse, SimilarJournalsBundle, WorksPage } from "@/lib/api";
import { journalWorksRequest, similarRequest } from "@/lib/api";
import { docPage, pageContext } from "@/lib/page-meta";
import { qk } from "@/lib/query-keys";
import { fetchOrNotFound, fetchForRender } from "@/lib/server-fetch";

type JournalRoute = { params: Promise<{ inst: string; issn_l: string }> };

/** The journal document the page reads before a funder or year lens is set. */
function loadJournal(inst: string, issnL: string) {
  return fetchOrNotFound<JournalDetailResponse>({
    path: `/${inst}/journals/${issnL}`,
    query: { include_gaps: "false" },
  });
}

/** The documents the page reads on first paint with defaults (no funder, no
 * year lens, works page 1). A ?page=N URL seeds only page 1; the browser
 * fetches the requested page. */
function loadJournalSections(inst: string, issnL: string) {
  return Promise.all([
    fetchForRender<SimilarJournalsBundle>(similarRequest(inst, issnL)),
    fetchForRender<WorksPage>(journalWorksRequest(inst, issnL, 1)),
  ]);
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
  const [[similar, works], journal] = await Promise.all([
    loadJournalSections(inst, issnL),
    loadJournal(inst, issnL),
  ]);
  return (
    <SectionMessages namespaces={["journals", "authors", "orgunits", "publishers", "shortlist"]}>
      <Seeds
        entries={[
          { queryKey: qk.journal(inst, issnL), data: journal },
          { queryKey: qk.similar(inst, issnL), data: similar },
          { queryKey: qk.works(inst, issnL, 1), data: works },
        ]}
      >
        {children}
      </Seeds>
    </SectionMessages>
  );
}
