import { PAGE_SIZE, readCollabParams } from "@/components/collaborations/collab-params";
import { Seeds } from "@/components/seed";
import {
  collaborationRequest,
  collaborationWorksRequest,
  type CollaborationDetailResponse,
  type CollaborationWorksResponse,
} from "@/lib/api";
import { type RouteSearchParams, urlSearchParams } from "@/lib/page-meta";
import { qk } from "@/lib/query-keys";
import { fetchOrNotFound, fetchForRender } from "@/lib/server-fetch";

import PartnerPageClient from "./page-client";

type PartnerRoute = {
  params: Promise<{ inst: string; ror: string }>;
  searchParams: RouteSearchParams;
};

/** The URL's filter set. The year lens is not stored in the URL and reads
 * localStorage after mount, so the first client render fetches without
 * `year_from`/`year_to`, exactly as this seed does. */
async function filtersFrom(searchParams: RouteSearchParams) {
  return readCollabParams(await urlSearchParams(searchParams));
}

/** Seeds the partner document and its first works page (the works card keeps
 * the query mounted even while collapsed), so the page renders its real
 * content on the server and the browser fetches nothing. An unknown partner
 * renders the not-found page: fetchOrNotFound turns the backend's 404 into
 * the route's 404, as the layout's metadata fetch already does. */
export default async function PartnerPage({ params, searchParams }: PartnerRoute) {
  const { inst, ror } = await params;
  const filters = await filtersFrom(searchParams);
  const offset = 0; // the works pager is client state and starts at page 1
  const [doc, works] = await Promise.all([
    fetchOrNotFound<CollaborationDetailResponse>(collaborationRequest(inst, ror, filters)),
    fetchForRender<CollaborationWorksResponse>(
      collaborationWorksRequest(inst, ror, filters, offset, PAGE_SIZE),
    ),
  ]);
  return (
    <Seeds
      entries={[
        { queryKey: qk.collaboration(inst, ror, filters), data: doc },
        {
          queryKey: [...qk.collaborationWorks(inst, ror, filters, offset), PAGE_SIZE] as const,
          data: works,
        },
      ]}
    >
      <PartnerPageClient />
    </Seeds>
  );
}
