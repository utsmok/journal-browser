"use client";

import { keepPreviousData, useQuery, type Query } from "@tanstack/react-query";
import * as React from "react";

import { useInstitution } from "./use-institution";
import { trackSearch } from "@/lib/usage/tracker";
import {
  apiGet,
  COLLAB_MULTI_KEYS,
  fetchAuthor,
  fetchCollaboration,
  fetchCollaborationMap,
  fetchCollaborations,
  fetchCollaborationWorks,
  fetchJournalBatch,
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
import { qk } from "@/lib/query-keys";
import type { InstitutionDirectoryEntry } from "@/lib/admin";

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

/**
 * Placeholder for detail queries. A stored funder or year lens keys a scoped
 * variant of the query the server rendered; while that variant loads, the
 * unscoped data stays on screen instead of the skeleton. The entity must be
 * the same (the key without its scope): opening another journal still shows
 * the skeleton.
 */
function keepDataForSameEntity<T>(entityKey: readonly unknown[]) {
  return (previousData: T | undefined, previousQuery: Query<T> | undefined): T | undefined =>
    previousQuery && entityKey.every((part, index) => previousQuery.queryKey[index] === part)
      ? previousData
      : undefined;
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
            // The eligibility toggles apply to semantic search too; both are
            // server-side defaults, so they travel only when switched off.
            active: params.active,
            vouched: params.vouched,
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
    staleTime: 60_000,
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
    queryKey: qk.journal(
      inst,
      issnL ?? "",
      funderId ?? null,
      years?.year_from ?? null,
      years?.year_to ?? null,
    ),
    queryFn: () =>
      apiGet<JournalDetailResponse>(`/${inst}/journals/${issnL}`, {
        funder: funderId,
        year_from: years?.year_from,
        year_to: years?.year_to,
        include_gaps: "false",
      }),
    enabled: Boolean(issnL),
    placeholderData: keepDataForSameEntity(qk.journal(inst, issnL ?? "")),
    staleTime: 60_000,
  });
}

/** Author profile bundle (OA trend, journals, works); authorId is a Pure UUID. */
export function useAuthor(authorId: string | undefined, years?: YearParams) {
  const inst = useInstitution();
  return useQuery({
    queryKey: qk.author(inst, authorId ?? "", years?.year_from ?? null, years?.year_to ?? null),
    queryFn: () => fetchAuthor(inst, authorId ?? "", years),
    enabled: Boolean(authorId),
    placeholderData: keepDataForSameEntity(qk.author(inst, authorId ?? "")),
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
    queryFn: () => fetchJournalBatch(inst, issnLs, years),
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
    staleTime: 60_000,
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
    queryKey: qk.institutions(),
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
    queryKey: qk.publisher(inst, name ?? "", years?.year_from ?? null, years?.year_to ?? null),
    queryFn: () => fetchPublisher(inst, name ?? "", years, undefined, false),
    enabled: Boolean(name),
    placeholderData: keepDataForSameEntity(qk.publisher(inst, name ?? "")),
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
    queryKey: qk.orgunit(
      inst,
      level ?? "faculty",
      name ?? "",
      years?.year_from ?? null,
      years?.year_to ?? null,
      sort ?? "share",
    ),
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
    queryKey: qk.funder(inst, id ?? 0, years?.year_from ?? null, years?.year_to ?? null),
    queryFn: () =>
      apiGet<FunderDetailResponse>(`/${inst}/funders/${id}`, {
        year_from: years?.year_from,
        year_to: years?.year_to,
      }),
    enabled: Boolean(id) && inst !== "",
    placeholderData: keepDataForSameEntity(qk.funder(inst, id ?? 0)),
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
