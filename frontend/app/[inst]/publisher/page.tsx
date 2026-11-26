import { Seeds } from "@/components/seed";
import { type PublisherSearchResponse, publishersRequest } from "@/lib/api";
import { type InstRoute, type RouteSearchParams, urlSearchParams } from "@/lib/page-meta";
import { qk } from "@/lib/query-keys";
import { fetchForRender } from "@/lib/server-fetch";

import PublishersPageClient from "./page-client";
import { publisherDirectoryParams } from "./params";

type PublishersRoute = InstRoute & { searchParams: RouteSearchParams };

/** Seeds the publisher directory list (facets ride along in the response),
 * so the server HTML carries the rows and facet counts and the browser finds
 * them instead of refetching. The site meta the page also reads is seeded by
 * app/[inst]/layout. */
export default async function PublishersPage({ params, searchParams }: PublishersRoute) {
  const { inst } = await params;
  // The year lens hydrates after mount, so the first client render runs
  // over the full data window; the seed uses the same empty range.
  const { params: directory } = publisherDirectoryParams(await urlSearchParams(searchParams));
  const list = await fetchForRender<PublisherSearchResponse>(publishersRequest(inst, directory));
  return (
    <Seeds entries={[{ queryKey: qk.publishers(inst, directory), data: list }]}>
      <PublishersPageClient />
    </Seeds>
  );
}
