import { Seeds } from "@/components/seed";
import { type DocDetail, type DocsListItem, docsRequest } from "@/lib/docs";
import { qk } from "@/lib/query-keys";
import { fetchOrNotFound, fetchForRender } from "@/lib/server-fetch";

import DocPageClient from "./page-client";

type DocRoute = { params: Promise<{ inst: string; slug: string }> };

/** Seeds the document and the index, so the page renders its content on the
 * server. An unknown slug is a real 404: fetchOrNotFound renders the
 * not-found page when the backend answers 404. */
export default async function DocPage({ params }: DocRoute) {
  const { inst, slug } = await params;
  const [doc, docs] = await Promise.all([
    fetchOrNotFound<DocDetail>({ path: `/docs/${encodeURIComponent(slug)}` }),
    fetchForRender<DocsListItem[]>(docsRequest()),
  ]);
  return (
    <Seeds
      entries={[
        { queryKey: qk.doc(inst, slug), data: doc },
        { queryKey: qk.docs(inst), data: docs },
      ]}
    >
      <DocPageClient />
    </Seeds>
  );
}
