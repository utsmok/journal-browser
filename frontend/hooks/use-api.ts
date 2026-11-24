"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import * as React from "react";

import { useInstitution } from "./use-institution";
import { trackSearch } from "@/lib/usage/tracker";
import {
  apiGet,
  COLLAB_MULTI_KEYS,
  fetchCollaboration,
  fetchCollaborationMap,
  fetchCollaborations,
  fetchCollaborationWorks,
  fetchJournalCrisGaps,
  fetchOrgUnit,
  fetchOrgUnitCrisGaps,
  fetchOrgUnits,
  fetchPublisher,
  fetchPublisherCrisGaps,
  fetchPublishers,
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
  type PublisherPartsFilter,
  type PublisherSearchParams,
  type SimilarJournalsBundle,
  type WorksPage,
  type YearParams,
} from "@/lib/api";
import type { InstitutionDirectoryEntry } from "@/lib/admin";

/** TanStack Query key factory: one place owns every cache key shape.
 * Every key leads with the institution code — two hosted universities
 * must never share cache entries. */
const qk = {
  journals: (i: string, params: JournalSearchParams) => ["journals", i, params] as const,
  facets: (i: string, filters: JournalSearchParams) => ["facets", i, filters] as const,
  journal: (i: string, issnL: string) => ["journal", i, issnL] as const,
  journalGaps: (i: string, issnL: string) => ["journal-gaps", i, issnL] as const,
  similar: (i: string, issnL: string) => ["similar", i, issnL] as const,
  works: (i: string, issnL: string, page: number) => ["works", i, issnL, page] as const,
  deals: (i: string, status: "current" | "archive" | "all") => ["deals", i, status] as const,
  limitations: (i: string) => ["limitations", i] as const,
  freshness: (i: string) => ["freshness", i] as const,
  publishers: (i: string, params: PublisherSearchParams) => ["publishers", i, params] as const,
  publisher: (i: string, name: string) => ["publisher", i, name] as const,
  publisherGaps: (i: string, name: string) => ["publisher-gaps", i, name] as const,
  orgunits: (i: string, params: OrgUnitSearchParams) => ["orgunits", i, params] as const,
  orgunit: (i: string, level: OrgUnitLevel, name: string) => ["orgunit", i, level, name] as const,
  orgunitGaps: (i: string, level: OrgUnitLevel, name: string) =>
    ["orgunit-gaps", i, level, name] as const,
  funders: (i: string, q: string) => ["funders", i, q] as const,
  funder: (i: string, id: number) => ["funder", i, id] as const,
  collaborations: (i: string, p: CollaborationSearchParams, offset: number) =>
    ["collaborations", i, p, offset] as const,
  collaborationMap: (i: string, p: CollaborationSearchParams) =>
    ["collaboration-map", i, p] as const,
  collaboration: (i: string, ror: string, p: CollaborationSearchParams) =>
    ["collaboration", i, ror, p] as const,
  collaborationWorks: (i: string, ror: string, p: CollaborationSearchParams, offset: number) =>
    ["collaboration-works", i, ror, p, offset] as const,
};

/**
 * Fetch-epoch guard: bumps a ref whenever the serialized params change, so an
 * in-flight response that lands after the params moved on is recognized as
 * stale and discarded instead of feeding the current view.
 */
function useFetchEpoch(params: JournalSearchParams) {
  const key = JSON.stringify(params);
  // Adjusting state during render (React's sanctioned "derive state from
  // the previous props" pattern): a params change bumps the epoch without
  // a committed extra render. A ref write here would also mutate on
  // renders React later throws away.
  const [state, setState] = React.useState({ key, epoch: 0 });
  if (state.key !== key) {
    setState({ key, epoch: state.epoch + 1 });
  }
  return state.epoch;
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
  const epoch = useFetchEpoch(params);
  return useQuery({
    queryKey: [...qk.journals(inst, params), semantic ? "semantic" : "fts"] as const,
    queryFn: async () => {
      const at = epoch;
      const data = semantic
        ? // Free-text "journals like this description": embeddings, not FTS.
          // Filter/sort params do not apply to the vector ranking, but the
          // cursor does: the endpoint pages by offset into its ranking.
          await apiGet<JournalSearchResponse>(`/${inst}/journals/semantic-search`, {
            q: params.q ?? "",
            limit: params.limit ?? 40,
            cursor: params.cursor,
          })
        : await apiGet<JournalSearchResponse>(`/${inst}/journals`, {
            ...params,
          });
      if (at !== epoch) throw new Error("stale fetch discarded");
      trackSearch({
        query: params.q ?? "",
        results_count: data.total,
        search_scope: "journals",
        // Filter/sort params do not apply to the semantic ranking.
        filters: semantic ? undefined : usageFilters(params),
      });
      return data;
    },
    placeholderData: keepPreviousData,
  });
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
  const { cursor: _c, sort: _s, limit: _l, q: _q, search_in: _si, ...filters } = params;
  return useQuery({
    queryKey: qk.facets(inst, filters),
    queryFn: () =>
      apiGet<JournalSearchResponse>(`/${inst}/journals`, {
        ...filters,
        include_facets: true,
        limit: 1,
      }),
    enabled,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}

export function useJournal(issnL: string | undefined, funderId?: number, years?: YearParams) {
  const inst = useInstitution();
  return useQuery({
    queryKey: [
      ...qk.journal(inst, issnL ?? ""),
      funderId ?? null,
      years?.year_from ?? null,
      years?.year_to ?? null,
    ] as const,
    queryFn: () =>
      apiGet<JournalDetailResponse>(`/${inst}/journals/${issnL}`, {
        funder: funderId,
        year_from: years?.year_from,
        year_to: years?.year_to,
        include_gaps: "false",
      }),
    enabled: Boolean(issnL),
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
    queryFn: () => fetchJournalCrisGaps(inst, issnL ?? "", years, parts),
    enabled: Boolean(issnL) && inst !== "" && enabled,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
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
    queryFn: () => apiGet<SimilarJournalsBundle>(`/${inst}/journals/${issnL}/similar`),
    enabled: Boolean(issnL),
    retry: false,
    staleTime: 60_000,
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
    queryKey: [
      ...qk.works(inst, issnL ?? "", page),
      years?.year_from ?? null,
      years?.year_to ?? null,
    ] as const,
    queryFn: () =>
      apiGet<WorksPage>(`/${inst}/journals/${issnL}/works`, {
        page,
        page_size: 10,
        year_from: years?.year_from,
        year_to: years?.year_to,
      }),
    enabled: Boolean(issnL),
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: 60_000,
  });
}

export function useDeals(
  status: "current" | "archive" | "all" = "current",
  { enabled = true }: { enabled?: boolean } = {},
) {
  const inst = useInstitution();
  return useQuery({
    queryKey: qk.deals(inst, status),
    queryFn: () => apiGet<DealOut[]>(`/${inst}/deals`, { status }),
    enabled: enabled && inst !== "",
    placeholderData: keepPreviousData,
  });
}

export function useLimitations() {
  const inst = useInstitution();
  return useQuery({
    queryKey: qk.limitations(inst),
    queryFn: () => apiGet<LimitationOut[]>(`/${inst}/meta/limitations`),
    staleTime: 10 * 60_000,
  });
}

/** Global directory of hosted institutions (unscoped endpoint). */
export function useInstitutionsDirectory() {
  return useQuery({
    queryKey: ["institutions"] as const,
    queryFn: () => apiGet<InstitutionDirectoryEntry[]>("/institutions"),
    staleTime: 10 * 60_000,
  });
}

export function useFreshness(instOverride?: string) {
  const ctxInst = useInstitution();
  const inst = instOverride ?? ctxInst;
  return useQuery({
    queryKey: qk.freshness(inst),
    queryFn: () => apiGet<FreshnessResponse>(`/${inst}/meta/freshness`),
    // Global pages (landing, /admin) have no institution segment; querying
    // //meta/freshness would just 404.
    enabled: inst !== "",
  });
}

/** Publisher browse list; facets are bundled in the response. */
export function usePublishers(params: PublisherSearchParams) {
  const inst = useInstitution();
  return useQuery({
    queryKey: qk.publishers(inst, params),
    queryFn: () => fetchPublishers(inst, params),
    placeholderData: keepPreviousData,
  });
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
    queryKey: [
      ...qk.publisher(inst, name ?? ""),
      years?.year_from ?? null,
      years?.year_to ?? null,
    ] as const,
    queryFn: () => fetchPublisher(inst, name ?? "", years, undefined, false),
    enabled: Boolean(name),
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
    queryFn: () => fetchPublisherCrisGaps(inst, name ?? "", years, parts),
    enabled: Boolean(name) && inst !== "" && enabled,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}

/** Org-unit browse list (faculties or research groups). */
export function useOrgUnits(params: OrgUnitSearchParams) {
  const inst = useInstitution();
  return useQuery({
    queryKey: qk.orgunits(inst, params),
    queryFn: () => fetchOrgUnits(inst, params),
    placeholderData: keepPreviousData,
  });
}

export function useOrgUnit(
  level: OrgUnitLevel | undefined,
  name: string | undefined,
  years?: YearParams,
  sort?: OrgUnitAuthorSort,
) {
  const inst = useInstitution();
  return useQuery({
    queryKey: [
      ...qk.orgunit(inst, level ?? "faculty", name ?? ""),
      years?.year_from ?? null,
      years?.year_to ?? null,
      sort ?? "share",
    ] as const,
    queryFn: () => fetchOrgUnit(inst, level ?? "faculty", name ?? "", years, sort, false),
    enabled: Boolean(level && name),
    placeholderData: keepPreviousData,
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
    queryFn: () => fetchOrgUnitCrisGaps(inst, level ?? "faculty", name ?? "", years, parts),
    enabled: Boolean(level && name) && inst !== "" && enabled,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}

/** Funder picker suggestions: name-substring search over the Jisc OPF
 * canon (~200 rows, server-filtered). Disabled until 2 chars. */
export function useFunders(q: string | undefined, enabled: boolean) {
  const inst = useInstitution();
  return useQuery({
    queryKey: qk.funders(inst, q ?? ""),
    queryFn: () => apiGet<FunderSearchResponse>(`/${inst}/funders`, { q, limit: 10 }),
    enabled: enabled && Boolean(q && q.trim().length >= 2) && inst !== "",
    placeholderData: keepPreviousData,
  });
}

/** Funder directory listing: paged, faceted, and year-scoped over the canon. */
export function useFunderDirectory(params: FunderSearchParams) {
  const inst = useInstitution();
  return useQuery({
    queryKey: [...qk.funders(inst, params.q ?? ""), params] as const,
    queryFn: async () => {
      const data = await apiGet<FunderSearchResponse>(`/${inst}/funders`, {
        q: params.q || undefined,
        country: params.country?.join("|"),
        policy_structured:
          params.policy_structured === undefined ? undefined : String(params.policy_structured),
        has_works: params.has_works === undefined ? undefined : String(params.has_works),
        oa_publishing: params.oa_publishing?.join("|"),
        green_archiving: params.green_archiving?.join("|"),
        data_policy: params.data_policy?.join("|"),
        sort: params.sort,
        dir: params.dir,
        offset: params.offset ?? 0,
        limit: params.limit ?? 50,
        year_from: params.year_from,
        year_to: params.year_to,
      });
      trackSearch({
        query: params.q ?? "",
        results_count: data.total,
        search_scope: "funders",
      });
      return data;
    },
    enabled: inst !== "",
    placeholderData: keepPreviousData,
  });
}

export function useFunder(id: number | undefined, years?: YearParams) {
  const inst = useInstitution();
  return useQuery({
    queryKey: [
      ...qk.funder(inst, id ?? 0),
      years?.year_from ?? null,
      years?.year_to ?? null,
    ] as const,
    queryFn: () =>
      apiGet<FunderDetailResponse>(`/${inst}/funders/${id}`, {
        year_from: years?.year_from,
        year_to: years?.year_to,
      }),
    enabled: Boolean(id) && inst !== "",
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
  return useQuery({
    queryKey: qk.collaborations(inst, params, offset),
    queryFn: async () => {
      const data = await fetchCollaborations(inst, params, offset);
      trackSearch({
        query: params.q ?? "",
        results_count: data.total_partners,
        search_scope: "collaborations",
        filters: collabUsageFilters(params),
      });
      return data;
    },
    enabled: inst !== "",
    placeholderData: keepPreviousData,
  });
}

export function useCollaborationMap(params: CollaborationSearchParams) {
  const inst = useInstitution();
  return useQuery({
    queryKey: qk.collaborationMap(inst, params),
    queryFn: () => fetchCollaborationMap(inst, params),
    enabled: inst !== "",
    placeholderData: keepPreviousData,
  });
}

export function useCollaboration(ror: string | undefined, params: CollaborationSearchParams) {
  const inst = useInstitution();
  return useQuery({
    queryKey: qk.collaboration(inst, ror ?? "", params),
    queryFn: () => fetchCollaboration(inst, ror ?? "", params),
    enabled: Boolean(ror) && inst !== "",
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
    queryFn: () => fetchCollaborationWorks(inst, ror, params, offset, limit),
    enabled: inst !== "",
    placeholderData: keepPreviousData,
  });
}
