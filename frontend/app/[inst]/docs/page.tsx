import { Seed } from "@/components/seed";
import { type DocsListItem, docsRequest } from "@/lib/docs";
import type { InstRoute } from "@/lib/page-meta";
import { qk } from "@/lib/query-keys";
import { fetchForRender } from "@/lib/server-fetch";

import DocsIndexPageClient from "./page-client";

/** Seeds the doc list, so the index renders its entries on the server. */
export default async function DocsIndexPage({ params }: InstRoute) {
  const { inst } = await params;
  const docs = await fetchForRender<DocsListItem[]>(docsRequest());
  return (
    <Seed queryKey={qk.docs(inst)} data={docs}>
      <DocsIndexPageClient />
    </Seed>
  );
}
