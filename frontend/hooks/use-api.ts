"use client";

import { keepPreviousData, useQuery, type Query } from "@tanstack/react-query";
import * as React from "react";

import { useInstitution } from "./use-institution";
import { trackSearch } from "@/lib/usage/tracker";
import {
  apiGet,
  authorsRequest,
  COLLAB_MULTI_KEYS,
  dealsRequest,
  facetFilters,
  facetsRequest,
  fetchAuthor,
  fetchCollaboration,
  fetchCollaborationMap,
  fetchCollaborations,
  fetchCollaborationWorks,
  fetchJournalBatch,
  fetchJournalCrisGaps,
  fetchOrgUnit,
  fetchOrgUnitCrisGaps,
  fetchPublisher,
  fetchPublisherCrisGaps,
  freshnessRequest,
  funderDirectoryRequest,
  getRequest,
  institutionsRequest,
  journalsRequest,
  journalWorksRequest,
  limitationsRequest,
  orgUnitsRequest,
  publishersRequest,
  similarRequest,
  usageDirectoryFilters,
  type AuthorFetchOptions,
  type AuthorSearchFilters,
  type AuthorSearchResponse,
  type CollaborationSearchParams,
  type CrisGapsResponse,
  type DealOut,
  type FreshnessResponse,
  type FunderDetailResponse,
  type FunderSearchParams,
  type FunderSearchResponse,
  type JournalDetailResponse,
  type JournalSearchParams,
  type JournalSearchResponse,
  type LimitationOut,
  type OrgUnitAuthorSort,
  type OrgUnitLevel,
  type OrgUnitSearchParams,
  type OrgUnitSearchResponse,
  type PublisherPartsFilter,
  type PublisherSearchParams,
  type PublisherSearchResponse,
  type SimilarJournalsBundle,
  type WorksPage,
  type YearParams,
} from "@/lib/api";
import { qk } from "@/lib/query-keys";
import type { InstitutionDirectoryEntry } from "@/lib/admin";

/**
 * Placeholder for detail queries. A stored funder or year lens keys a scoped
 * variant of the query the server rendered; while that variant loads, the
 * unscoped data stays on screen instead of the skeleton. The entity must be
 * the same (the key without its scope): opening another journal still shows
 * the skeleton.
 */
function keepDataForSameEntity(entityKey: readonly unknown[]) {
  return <T>(previousData: T | undefined, previousQuery: Query<T> | undefined): T | undefined =>
    previousQuery && entityKey.every((part, index) => previousQuery.queryKey[index] === part)
      ? previousData
      : undefined;
}

type SearchEvent = Parameters<typeof trackSearch>[0];

/**
 * Records one search usage event per result a list shows, whether the
 * browser fetched it or the server rendered it into the cache. Tracking from
 * the query function would miss every server-rendered first view. A
 * placeholder (the previous result kept on screen while the next loads) is
 * not a result.
 */
function useSearchEvent<T>(
  query: { data: T | undefined; dataUpdatedAt: number; isPlaceholderData: boolean },
  event: (data: T) => SearchEvent,
) {
  const { data, dataUpdatedAt, isPlaceholderData } = query;
  const record = React.useEffectEvent((shown: T) => trackSearch(event(shown)));
  React.useEffect(() => {
    if (data !== undefined && !isPlaceholderData) record(data);
  }, [data, dataUpdatedAt, isPlaceholderData]);
}

/** Filter keys stored on a usage search event; paging/sort keys dropped. */
const FILTER_KEYS = [
  "search_in",
  "deal",
  "deal_id",
  "oa",
  "doaj",
  "quartile",
  "publisher",
  "has_apc",
  "has_works",
  "topic",
  "oa_type",
  "pub_type",
  "language",
  "green_oa",
  "funder",
  "funder_fit",
  "active",
  "vouched",
] as const;

function usageFilters(params: JournalSearchParams): Record<string, unknown> | undefined {
  const out: Record<string, unknown> = {};
  for (const key of FILTER_KEYS) {
    if (params[key] !== undefined) out[key] = params[key];
  }
  return Object.keys(out).length ? out : undefined;
}

export function useJournals(params: JournalSearchParams, semantic?: boolean) {
  const inst = useInstitution();
  const query = useQuery({
    queryKey: qk.journalsSearch(inst, params, Boolean(semantic)),
    queryFn: ({ signal }) =>
      getRequest<JournalSearchResponse>(journalsRequest(inst, params, Boolean(semantic)), signal),
    placeholderData: keepPreviousData,
  });
  useSearchEvent(query, (data) => ({
    query: params.q ?? "",
    results_count: data.total,
    search_scope: "journals",
    // Filter/sort params do not apply to the semantic ranking.
    filters: semantic ? undefined : usageFilters(params),
  }));
  return query;
}

/**
 * Facets depend on the filter set only — never on cursor, page, or sort — so
 * they live in their own query and page turns reuse the cached aggregate.
 */
export function useFacets(
  params: JournalSearchParams,
  { enabled = true }: { enabled?: boolean } = {},
) {
  // Facet counts ignore the free-text query (and scope): a zero-hit query
  // must still show which filter values exist to pivot to, Scopus-style.
  const inst = useInstitution();
  const filters = facetFilters(params);
  return useQuery({
    queryKey: qk.facets(inst, filters),
    queryFn: ({ signal }) =>
      getRequest<JournalSearchResponse>(facetsRequest(inst, filters), signal),
    enabled,
    placeholderData: keepPreviousData,
  });
}

export function useJournal(issnL: string | undefined, funderId?: number, years?: YearParams) {
  const inst = useInstitution();
  return useQuery({
    queryKey: qk.journal(
      inst,
      issnL ?? "",
      funderId ?? null,
      years?.year_from ?? null,
      years?.year_to ?? null,
    ),
    queryFn: ({ signal }) =>
      apiGet<JournalDetailResponse>(
        `/${inst}/journals/${encodeURIComponent(issnL ?? "")}`,
        {
          funder: funderId,
          year_from: years?.year_from,
          year_to: years?.year_to,
          include_gaps: "false",
        },
        signal,
      ),
    enabled: Boolean(issnL),
    placeholderData: keepDataForSameEntity(["journal", inst, issnL ?? ""]),
  });
}

/** Author profile bundle (OA trend, journals, works); authorId is a Pure UUID. */
export function useAuthor(authorId: string | undefined, years?: YearParams) {
  const inst = useInstitution();
  return useQuery({
    queryKey: qk.author(inst, authorId ?? "", years?.year_from ?? null, years?.year_to ?? null),
    queryFn: ({ signal }) => fetchAuthor(inst, authorId ?? "", years, signal),
    enabled: Boolean(authorId),
    placeholderData: keepDataForSameEntity(["author", inst, authorId ?? ""]),
  });
}

/** Saved-journal rows (shortlist). The key carries the ordered ISSN-L list,
 * so a removed journal triggers a refetch; the year lens scopes the works
 * column. Previous data stays on screen meanwhile, so callers should show
 * only the rows still on their list. */
export function useJournalBatch(issnLs: string[], years?: YearParams) {
  const inst = useInstitution();
  return useQuery({
    queryKey: qk.journalBatch(inst, issnLs, years ?? {}),
    queryFn: ({ signal }) => fetchJournalBatch(inst, issnLs, years, signal),
    enabled: issnLs.length > 0,
    placeholderData: keepPreviousData,
  });
}

export function useJournalCrisGaps(
  issnL: string | undefined,
  years?: YearParams,
  parts?: PublisherPartsFilter,
  enabled: boolean = true,
) {
  const inst = useInstitution();
  return useQuery<CrisGapsResponse>({
    queryKey: [
      ...qk.journalGaps(inst, issnL ?? ""),
      years?.year_from ?? null,
      years?.year_to ?? null,
      parts ?? null,
    ] as const,
    queryFn: ({ signal }) => fetchJournalCrisGaps(inst, issnL ?? "", years, parts, signal),
    enabled: Boolean(issnL) && inst !== "" && enabled,
    placeholderData: keepPreviousData,
  });
}

/**
 * Similar journals for a title, in three cuts (institution-publishing,
 * deal-covered, general). Callers hide the section on error, so failures
 * are quiet and never retried.
 */
export function useSimilar(issnL: string | undefined) {
  const inst = useInstitution();
  return useQuery({
    queryKey: qk.similar(inst, issnL ?? ""),
    queryFn: ({ signal }) =>
      getRequest<SimilarJournalsBundle>(similarRequest(inst, issnL ?? ""), signal),
    enabled: Boolean(issnL),
    retry: false,
  });
}

/**
 * Institution works for a journal (OpenAlex). The section renders its
 * empty state on error, so failures stay quiet. The year lens, when set,
 * scopes the list and joins the cache key.
 */
export function useJournalWorks(issnL: string | undefined, page: number, years?: YearParams) {
  const inst = useInstitution();
  return useQuery({
    queryKey: qk.works(inst, issnL ?? "", page, years?.year_from ?? null, years?.year_to ?? null),
    queryFn: ({ signal }) =>
      getRequest<WorksPage>(journalWorksRequest(inst, issnL ?? "", page, years), signal),
    enabled: Boolean(issnL),
    placeholderData: keepPreviousData,
    retry: false,
  });
}

export function useDeals(
  status: "current" | "archive" | "all" = "current",
  { enabled = true }: { enabled?: boolean } = {},
) {
  const inst = useInstitution();
  return useQuery({
    queryKey: qk.deals(inst, status),
    queryFn: ({ signal }) => getRequest<DealOut[]>(dealsRequest(inst, status), signal),
    enabled: enabled && inst !== "",
    placeholderData: keepPreviousData,
  });
}

export function useLimitations() {
  const inst = useInstitution();
  return useQuery({
    queryKey: qk.limitations(inst),
    queryFn: ({ signal }) => getRequest<LimitationOut[]>(limitationsRequest(inst), signal),
    staleTime: 10 * 60_000,
  });
}

/** Global directory of hosted institutions (unscoped endpoint). */
export function useInstitutionsDirectory() {
  return useQuery({
    queryKey: qk.institutions(),
    queryFn: ({ signal }) => getRequest<InstitutionDirectoryEntry[]>(institutionsRequest(), signal),
    staleTime: 10 * 60_000,
  });
}

export function useFreshness(instOverride?: string) {
  const ctxInst = useInstitution();
  const inst = instOverride ?? ctxInst;
  return useQuery({
    queryKey: qk.freshness(inst),
    queryFn: ({ signal }) => getRequest<FreshnessResponse>(freshnessRequest(inst), signal),
    // Global pages (landing, /admin) have no institution segment; querying
    // //meta/freshness would just 404.
    enabled: inst !== "",
  });
}

/** Publisher browse list; facets are bundled in the response. */
export function usePublishers(params: PublisherSearchParams) {
  const inst = useInstitution();
  const query = useQuery({
    queryKey: qk.publishers(inst, params),
    queryFn: ({ signal }) =>
      getRequest<PublisherSearchResponse>(publishersRequest(inst, params), signal),
    placeholderData: keepPreviousData,
  });
  useSearchEvent(query, (data) => ({
    query: params.q ?? "",
    results_count: data.total,
    search_scope: "publishers",
    filters: usageDirectoryFilters(params),
  }));
  return query;
}

/**
 * Publisher detail bundle (loads fast with include_gaps=false; CRIS gaps are
 * fetched lazily via usePublisherCrisGaps when the section is opened).
 */
export function usePublisher(
  name: string | undefined,
  years?: YearParams,
  _parts?: PublisherPartsFilter,
) {
  const inst = useInstitution();
  return useQuery({
    queryKey: qk.publisher(inst, name ?? "", years?.year_from ?? null, years?.year_to ?? null),
    queryFn: ({ signal }) => fetchPublisher(inst, name ?? "", years, undefined, false, signal),
    enabled: Boolean(name),
    placeholderData: keepDataForSameEntity(["publisher", inst, name ?? ""]),
  });
}

export function usePublisherCrisGaps(
  name: string | undefined,
  years?: YearParams,
  parts?: PublisherPartsFilter,
  enabled: boolean = true,
) {
  const inst = useInstitution();
  return useQuery<CrisGapsResponse>({
    queryKey: [
      ...qk.publisherGaps(inst, name ?? ""),
      years?.year_from ?? null,
      years?.year_to ?? null,
      parts ?? null,
    ] as const,
    queryFn: ({ signal }) => fetchPublisherCrisGaps(inst, name ?? "", years, parts, signal),
    enabled: Boolean(name) && inst !== "" && enabled,
    placeholderData: keepPreviousData,
  });
}

/** Org-unit browse list (faculties or research groups). */
export function useOrgUnits(params: OrgUnitSearchParams) {
  const inst = useInstitution();
  const query = useQuery({
    queryKey: qk.orgunits(inst, params),
    queryFn: ({ signal }) =>
      getRequest<OrgUnitSearchResponse>(orgUnitsRequest(inst, params), signal),
    placeholderData: keepPreviousData,
  });
  useSearchEvent(query, (data) => ({
    query: params.q ?? "",
    results_count: data.total,
    search_scope: "orgunits",
    filters: usageDirectoryFilters(params),
  }));
  return query;
}

/** Author directory listing: facets ride along in the response. */
export function useAuthorDirectory(
  q: string | undefined,
  filters: AuthorSearchFilters,
  opts: AuthorFetchOptions,
) {
  const inst = useInstitution();
  const query = useQuery({
    queryKey: qk.authors(inst, q ?? null, filters, opts),
    queryFn: ({ signal }) =>
      getRequest<AuthorSearchResponse>(authorsRequest(inst, q, filters, opts), signal),
    placeholderData: keepPreviousData,
  });
  useSearchEvent(query, (data) => ({
    query: q ?? "",
    results_count: data.total,
    search_scope: "authors",
    filters: { ...filters },
  }));
  return query;
}

export function useOrgUnit(
  level: OrgUnitLevel | undefined,
  name: string | undefined,
  years?: YearParams,
  sort?: OrgUnitAuthorSort,
) {
  const inst = useInstitution();
  return useQuery({
    queryKey: qk.orgunit(
      inst,
      level ?? "faculty",
      name ?? "",
      years?.year_from ?? null,
      years?.year_to ?? null,
      sort ?? "share",
    ),
    queryFn: ({ signal }) =>
      fetchOrgUnit(inst, level ?? "faculty", name ?? "", years, sort, false, signal),
    enabled: Boolean(level && name),
    placeholderData: keepDataForSameEntity(["orgunit", inst, level ?? "faculty", name ?? ""]),
  });
}

export function useOrgUnitCrisGaps(
  level: OrgUnitLevel | undefined,
  name: string | undefined,
  years?: YearParams,
  parts?: PublisherPartsFilter,
  enabled: boolean = true,
) {
  const inst = useInstitution();
  return useQuery<CrisGapsResponse>({
    queryKey: [
      ...qk.orgunitGaps(inst, level ?? "faculty", name ?? ""),
      years?.year_from ?? null,
      years?.year_to ?? null,
      parts ?? null,
    ] as const,
    queryFn: ({ signal }) =>
      fetchOrgUnitCrisGaps(inst, level ?? "faculty", name ?? "", years, parts, signal),
    enabled: Boolean(level && name) && inst !== "" && enabled,
    placeholderData: keepPreviousData,
  });
}

/** Funder picker suggestions: name-substring search over the Jisc OPF
 * canon (~200 rows, server-filtered). Disabled until 2 chars. */
export function useFunders(q: string | undefined, enabled: boolean) {
  const inst = useInstitution();
  return useQuery({
    queryKey: qk.funders(inst, q ?? ""),
    queryFn: ({ signal }) =>
      apiGet<FunderSearchResponse>(`/${inst}/funders`, { q, limit: 10 }, signal),
    enabled: enabled && Boolean(q && q.trim().length >= 2) && inst !== "",
    placeholderData: keepPreviousData,
  });
}

/** Funder directory listing: paged, faceted, and year-scoped over the canon. */
export function useFunderDirectory(params: FunderSearchParams) {
  const inst = useInstitution();
  const query = useQuery({
    queryKey: qk.funderDirectory(inst, params),
    queryFn: ({ signal }) =>
      getRequest<FunderSearchResponse>(funderDirectoryRequest(inst, params), signal),
    enabled: inst !== "",
    placeholderData: keepPreviousData,
  });
  useSearchEvent(query, (data) => ({
    query: params.q ?? "",
    results_count: data.total,
    search_scope: "funders",
  }));
  return query;
}

export function useFunder(id: number | undefined, years?: YearParams) {
  const inst = useInstitution();
  return useQuery({
    queryKey: qk.funder(inst, id ?? 0, years?.year_from ?? null, years?.year_to ?? null),
    queryFn: ({ signal }) =>
      apiGet<FunderDetailResponse>(
        `/${inst}/funders/${id}`,
        {
          year_from: years?.year_from,
          year_to: years?.year_to,
        },
        signal,
      ),
    enabled: Boolean(id) && inst !== "",
    placeholderData: keepDataForSameEntity(["funder", inst, id ?? 0]),
  });
}

/** The multi-select filters of a partner search, kept on its usage event. */
function collabUsageFilters(p: CollaborationSearchParams): Record<string, unknown> {
  return Object.fromEntries(
    COLLAB_MULTI_KEYS.filter((key) => p[key]?.length).map((key) => [key, p[key]]),
  );
}

/** Partner list. The response carries the totals, facets and effective year
 * range of the whole filter set, not only of the page shown. */
export function useCollaborations(params: CollaborationSearchParams, offset: number) {
  const inst = useInstitution();
  const query = useQuery({
    queryKey: qk.collaborations(inst, params, offset),
    queryFn: ({ signal }) => fetchCollaborations(inst, params, offset, signal),
    enabled: inst !== "",
    placeholderData: keepPreviousData,
  });
  useSearchEvent(query, (data) => ({
    query: params.q ?? "",
    results_count: data.total_partners,
    search_scope: "collaborations",
    filters: collabUsageFilters(params),
  }));
  return query;
}

export function useCollaborationMap(params: CollaborationSearchParams) {
  const inst = useInstitution();
  return useQuery({
    queryKey: qk.collaborationMap(inst, params),
    queryFn: ({ signal }) => fetchCollaborationMap(inst, params, signal),
    enabled: inst !== "",
    placeholderData: keepPreviousData,
  });
}

export function useCollaboration(ror: string | undefined, params: CollaborationSearchParams) {
  const inst = useInstitution();
  return useQuery({
    queryKey: qk.collaboration(inst, ror ?? "", params),
    queryFn: ({ signal }) => fetchCollaboration(inst, ror ?? "", params, signal),
    enabled: Boolean(ror) && inst !== "",
    placeholderData: keepDataForSameEntity(["collaboration", inst, ror ?? ""]),
  });
}

export function useCollaborationWorks(
  ror: string,
  params: CollaborationSearchParams,
  offset: number,
  limit?: number,
) {
  const inst = useInstitution();
  return useQuery({
    queryKey: [...qk.collaborationWorks(inst, ror, params, offset), limit ?? null] as const,
    queryFn: ({ signal }) => fetchCollaborationWorks(inst, ror, params, offset, limit, signal),
    enabled: inst !== "",
    placeholderData: keepPreviousData,
  });
}
