import * as React from "react";

import { Seeds } from "@/components/seed";
import { JournalsLanding } from "@/components/search/journals-landing";
import { journalsLandingParams } from "@/components/search/params";
import {
  type DealOut,
  type JournalSearchResponse,
  dealsRequest,
  facetFilters,
  facetsRequest,
  journalsRequest,
} from "@/lib/api";
import { qk } from "@/lib/query-keys";
import { type InstRoute, type RouteSearchParams, urlSearchParams } from "@/lib/page-meta";
import { fetchForRender } from "@/lib/server-fetch";

/**
 * Seeds what the browse view shows on first paint: the result list, its
 * facet counts, and the deals list behind a deal_id chip. The guide view renders no list or facets and stays unseeded. The
 * funder pref and year lens hydrate from localStorage after mount, so the
 * seeded keys are the unscoped ones the first client render computes.
 */
export default async function HomePage({
  params,
  searchParams,
}: InstRoute & { searchParams: RouteSearchParams }) {
  const { inst } = await params;
  const parsed = journalsLandingParams(await urlSearchParams(searchParams));
  if (parsed.view !== "browse") {
    return (
      <React.Suspense fallback={null}>
        <JournalsLanding initialView="browse" />
      </React.Suspense>
    );
  }

  const filters = facetFilters(parsed.query);
  const [journals, facets, deals] = await Promise.all([
    fetchForRender<JournalSearchResponse>(journalsRequest(inst, parsed.query, parsed.semantic)),
    // In semantic mode the facets hook is disabled: nothing to seed.
    parsed.semantic ? null : fetchForRender<JournalSearchResponse>(facetsRequest(inst, filters)),
    parsed.dealId !== undefined ? fetchForRender<DealOut[]>(dealsRequest(inst, "all")) : null,
  ]);

  return (
    <React.Suspense fallback={null}>
      <Seeds
        entries={[
          { queryKey: qk.journalsSearch(inst, parsed.query, parsed.semantic), data: journals },
          { queryKey: qk.facets(inst, filters), data: facets },
          { queryKey: qk.deals(inst, "all"), data: deals },
        ]}
      >
        <JournalsLanding initialView="browse" />
      </Seeds>
    </React.Suspense>
  );
}
