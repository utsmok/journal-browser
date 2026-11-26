import { Seeds } from "@/components/seed";
import { funderDirectoryRequest, type FunderSearchResponse } from "@/lib/api";
import { type InstRoute, type RouteSearchParams, urlSearchParams } from "@/lib/page-meta";
import { qk } from "@/lib/query-keys";
import { fetchForRender } from "@/lib/server-fetch";

import FundersPageClient from "./page-client";
import { funderDirectoryParams } from "./params";

type FundersRoute = InstRoute & { searchParams: RouteSearchParams };

/** Seeds the funder directory list, so the server HTML carries the rows and
 * facet counts and the browser finds them instead of refetching. The site
 * meta the page also reads is seeded by app/[inst]/layout. */
export default async function FundersPage({ params, searchParams }: FundersRoute) {
  const { inst } = await params;
  // The year lens hydrates after mount, so the first client render runs
  // over the full data window; the seed uses the same empty range.
  const { params: directory } = funderDirectoryParams(await urlSearchParams(searchParams));
  const list = await fetchForRender<FunderSearchResponse>(funderDirectoryRequest(inst, directory));
  return (
    <Seeds entries={[{ queryKey: qk.funderDirectory(inst, directory), data: list }]}>
      <FundersPageClient />
    </Seeds>
  );
}
