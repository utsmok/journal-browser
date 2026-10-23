"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import * as React from "react";

import {
  apiGet,
  type DealOut,
  type FreshnessResponse,
  type JournalDetailResponse,
  type JournalSearchParams,
  type JournalSearchResponse,
  type LimitationOut,
  type SimilarJournal,
  type WorksPage,
} from "@/lib/api";

/** TanStack Query key factory: one place owns every cache key shape. */
export const qk = {
  journals: (params: JournalSearchParams) => ["journals", params] as const,
  journal: (issnL: string) => ["journal", issnL] as const,
  similar: (issnL: string) => ["similar", issnL] as const,
  works: (issnL: string, page: number) => ["works", issnL, page] as const,
  deals: (status: "current" | "archive" | "all") => ["deals", status] as const,
  limitations: () => ["limitations"] as const,
  freshness: () => ["freshness"] as const,
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

export function useJournals(params: JournalSearchParams) {
  const epoch = useFetchEpoch(params);
  return useQuery({
    queryKey: qk.journals(params),
    queryFn: async () => {
      const at = epoch.current;
      const data = await apiGet<JournalSearchResponse>("/journals", {
        ...params,
      });
      if (at !== epoch.current) throw new Error("stale fetch discarded");
      return data;
    },
    placeholderData: keepPreviousData,
  });
}

export function useJournal(issnL: string | undefined) {
  return useQuery({
    queryKey: qk.journal(issnL ?? ""),
    queryFn: () => apiGet<JournalDetailResponse>(`/journals/${issnL}`),
    enabled: Boolean(issnL),
  });
}

/**
 * Similar journals for a title. Old backends lack the route; callers hide the
 * section on error, so failures are quiet and never retried.
 */
export function useSimilar(issnL: string | undefined) {
  return useQuery({
    queryKey: qk.similar(issnL ?? ""),
    queryFn: () => apiGet<SimilarJournal[]>(`/journals/${issnL}/similar`),
    enabled: Boolean(issnL),
    retry: false,
    staleTime: 60_000,
  });
}

/**
 * Twente works for a journal (OpenAlex). Old backends lack the route; the
 * section renders its empty state on error, so failures stay quiet.
 */
export function useJournalWorks(issnL: string | undefined, page: number) {
  return useQuery({
    queryKey: qk.works(issnL ?? "", page),
    queryFn: () =>
      apiGet<WorksPage>(`/journals/${issnL}/works`, { page, page_size: 20 }),
    enabled: Boolean(issnL),
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: 60_000,
  });
}

export function useDeals(status: "current" | "archive" | "all" = "current") {
  return useQuery({
    queryKey: qk.deals(status),
    queryFn: () => apiGet<DealOut[]>("/deals", { status }),
    placeholderData: keepPreviousData,
  });
}

export function useLimitations() {
  return useQuery({
    queryKey: qk.limitations(),
    queryFn: () => apiGet<LimitationOut[]>("/meta/limitations"),
    staleTime: 10 * 60_000,
  });
}

export function useFreshness() {
  return useQuery({
    queryKey: qk.freshness(),
    queryFn: () => apiGet<FreshnessResponse>("/meta/freshness"),
  });
}
