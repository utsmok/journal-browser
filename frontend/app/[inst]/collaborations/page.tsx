import { readCollabParams } from "@/components/collaborations/collab-params";
import { Seeds } from "@/components/seed";
import { collaborationsRequest, type CollaborationSearchResponse } from "@/lib/api";
import { type RouteSearchParams, urlSearchParams } from "@/lib/page-meta";
import { qk } from "@/lib/query-keys";
import { fetchForRender } from "@/lib/server-fetch";

import CollaborationsPageClient from "./page-client";

type CollaborationsRoute = {
  params: Promise<{ inst: string }>;
  searchParams: RouteSearchParams;
};

/** The URL's filter set. The year lens is not stored in the URL and reads
 * localStorage after mount, so the first client render fetches without
 * `year_from`/`year_to`, exactly as this seed does. */
async function filtersFrom(searchParams: RouteSearchParams) {
  return readCollabParams(await urlSearchParams(searchParams));
}

/** Seeds the partner list, so the page renders its real rows, facet counts
 * and overview on the server. The map is left to the browser: it renders
 * client-side only (ssr: false), and its ~1 MB of points would multiply the
 * page's HTML for no server-rendered pixel. */
export default async function CollaborationsPage({ params, searchParams }: CollaborationsRoute) {
  const { inst } = await params;
  const filters = await filtersFrom(searchParams);
  const offset = 0; // the pager offset is client state and starts at 0
  const list = await fetchForRender<CollaborationSearchResponse>(
    collaborationsRequest(inst, filters, offset),
  );
  return (
    <Seeds entries={[{ queryKey: qk.collaborations(inst, filters, offset), data: list }]}>
      <CollaborationsPageClient />
    </Seeds>
  );
}
