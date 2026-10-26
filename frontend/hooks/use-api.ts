"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import * as React from "react";

import { useInstitution } from "./use-institution";
import {
  apiGet,
  type DealOut,
  type FreshnessResponse,
  type JournalDetailResponse,
  type JournalSearchParams,
  type JournalSearchResponse,
  type LimitationOut,
  type SimilarJournalsBundle,
  type WorksPage,
} from "@/lib/api";

/** TanStack Query key factory: one place owns every cache key shape.
 * Every key leads with the institution code — two hosted universities
 * must never share cache entries. */
const qk = {
  journals: (i: string, params: JournalSearchParams) => ["journals", i, params] as const,
  facets: (i: string, filters: JournalSearchParams) => ["facets", i, filters] as const,
  journal: (i: string, issnL: string) => ["journal", i, issnL] as const,
  similar: (i: string, issnL: string) => ["similar", i, issnL] as const,
  works: (i: string, issnL: string, page: number) => ["works", i, issnL, page] as const,
  deals: (i: string, status: "current" | "archive" | "all") => ["deals", i, status] as const,
  limitations: (i: string) => ["limitations", i] as const,
  freshness: (i: string) => ["freshness", i] as const,
};

/**
 * Fetch-epoch guard: bumps a ref whenever the serialized params change, so an
 * in-flight response that lands after the params moved on is recognized as
 * stale and discarded instead of feeding the current view.
 */
function useFetchEpoch(params: JournalSearchParams) {
  const epoch = React.useRef(0);
  const key = JSON.stringify(params);
  const prev = React.useRef(key);
  if (prev.current !== key) {
    prev.current = key;
    epoch.current += 1;
  }
  return epoch;
}

export function useJournals(params: JournalSearchParams, semantic?: boolean) {
  const inst = useInstitution();
  const epoch = useFetchEpoch(params);
  return useQuery({
    queryKey: [...qk.journals(inst, params), semantic ? "semantic" : "fts"] as const,
    queryFn: async () => {
      const at = epoch.current;
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
      if (at !== epoch.current) throw new Error("stale fetch discarded");
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
  const {
    cursor: _c,
    sort: _s,
    limit: _l,
    q: _q,
    search_in: _si,
    ...filters
  } = params;
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

export function useJournal(issnL: string | undefined) {
  const inst = useInstitution();
  return useQuery({
    queryKey: qk.journal(inst, issnL ?? ""),
    queryFn: () => apiGet<JournalDetailResponse>(`/${inst}/journals/${issnL}`),
    enabled: Boolean(issnL),
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
 * empty state on error, so failures stay quiet.
 */
export function useJournalWorks(issnL: string | undefined, page: number) {
  const inst = useInstitution();
  return useQuery({
    queryKey: qk.works(inst, issnL ?? "", page),
    queryFn: () =>
      apiGet<WorksPage>(`/${inst}/journals/${issnL}/works`, { page, page_size: 20 }),
    enabled: Boolean(issnL),
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: 60_000,
  });
}

export function useDeals(status: "current" | "archive" | "all" = "current") {
  const inst = useInstitution();
  return useQuery({
    queryKey: qk.deals(inst, status),
    queryFn: () => apiGet<DealOut[]>(`/${inst}/deals`, { status }),
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

export type InstitutionDirectoryEntry = {
  code: string;
  name: string;
  short_name: string | null;
  is_default: boolean;
  data_window_start: number;
  data_window_end: number | null;
  library_url: string | null;
  oa_guide_url: string | null;
  support_email: string | null;
  admin_contact: string | null;
  research_portal_url: string | null;
};

/** Global directory of hosted institutions (unscoped endpoint). */
export function useInstitutionsDirectory() {
  return useQuery({
    queryKey: ["institutions"] as const,
    queryFn: () => apiGet<InstitutionDirectoryEntry[]>("/institutions"),
    staleTime: 10 * 60_000,
  });
}

export function useFreshness() {
  const inst = useInstitution();
  return useQuery({
    queryKey: qk.freshness(inst),
    queryFn: () => apiGet<FreshnessResponse>(`/${inst}/meta/freshness`),
  });
}
