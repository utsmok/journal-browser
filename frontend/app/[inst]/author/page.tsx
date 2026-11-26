import { Seeds } from "@/components/seed";
import { authorsRequest, type AuthorSearchResponse } from "@/lib/api";
import { type InstRoute, type RouteSearchParams, urlSearchParams } from "@/lib/page-meta";
import { qk } from "@/lib/query-keys";
import { fetchForRender } from "@/lib/server-fetch";

import { authorDirectoryParams } from "./params";
import AuthorPageClient from "./page-client";

/** Seeds the author directory, so the server HTML already carries the rows
 * and facet counts and the browser does not fetch the list again. The seed
 * key is the one useAuthorDirectory computes on its first client render:
 * URL state, and the year lens still off (the stored selection loads after
 * mount). A failed fetch seeds nothing; the browser fetches as before. */
export default async function AuthorListPage({
  params,
  searchParams,
}: InstRoute & { searchParams: RouteSearchParams }) {
  const { inst } = await params;
  const sp = await urlSearchParams(searchParams);
  const p = authorDirectoryParams(sp);
  const data = await fetchForRender<AuthorSearchResponse>(
    authorsRequest(inst, p.query, p.filters, p.opts),
  );
  return (
    <Seeds entries={[{ queryKey: qk.authors(inst, p.query ?? null, p.filters, p.opts), data }]}>
      <AuthorPageClient />
    </Seeds>
  );
}
