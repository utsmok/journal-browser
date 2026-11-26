import { Seeds, type SeedEntry } from "@/components/seed";
import { orgUnitsRequest, type OrgUnitLevel, type OrgUnitSearchResponse } from "@/lib/api";
import { type InstRoute, type RouteSearchParams, urlSearchParams } from "@/lib/page-meta";
import { qk } from "@/lib/query-keys";
import { fetchForRender } from "@/lib/server-fetch";

import { orgUnitDirectoryParams } from "./params";
import OrgUnitPageClient from "./page-client";

/** Seeds the org-unit directory, so the server HTML already carries the rows
 * and facet counts and the browser does not fetch the list again. The seed
 * key is the one useOrgUnits computes on its first client render: URL state,
 * and the year lens still off (the stored selection loads after mount). A
 * failed fetch seeds nothing; the browser fetches as before. */
export default async function OrgUnitListPage({
  params,
  searchParams,
}: InstRoute & { searchParams: RouteSearchParams }) {
  const { inst } = await params;
  const sp = await urlSearchParams(searchParams);
  const p = orgUnitDirectoryParams(sp);
  const data = await fetchForRender<OrgUnitSearchResponse>(orgUnitsRequest(inst, p.request));
  const entries: SeedEntry[] = [{ queryKey: qk.orgunits(inst, p.request), data }];
  // A query that misses the current level with no filters renders the other
  // rosters on first paint (CrossLevelMatches); seed those lookups under the
  // exact keys those components use, and only when they actually mount.
  if (p.query && p.faculty.length === 0 && p.works.length === 0 && !p.usesDeals) {
    const others = (["faculty", "group", "institute"] as const)
      .filter((level): level is OrgUnitLevel => level !== p.level)
      .map((level) => {
        const crossRequest = { level, q: p.query, include_facets: false, limit: 3 } as const;
        return fetchForRender<OrgUnitSearchResponse>(
          orgUnitsRequest(inst, { ...crossRequest }),
        ).then((crossData) => ({
          queryKey: qk.orgunits(inst, { ...crossRequest }),
          data: crossData,
        }));
      });
    entries.push(...(await Promise.all(others)));
  }
  return (
    <Seeds entries={entries}>
      <OrgUnitPageClient />
    </Seeds>
  );
}
