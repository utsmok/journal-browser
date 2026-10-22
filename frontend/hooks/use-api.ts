"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import {
  apiGet,
  type DealOut,
  type FreshnessResponse,
  type JournalDetailResponse,
  type JournalSearchParams,
  type JournalSearchResponse,
  type LimitationOut,
} from "@/lib/api";

/** TanStack Query key factory: one place owns every cache key shape. */
export const qk = {
  journals: (params: JournalSearchParams) => ["journals", params] as const,
  journal: (issnL: string) => ["journal", issnL] as const,
  deals: (status: "current" | "archive" | "all") => ["deals", status] as const,
  limitations: () => ["limitations"] as const,
  freshness: () => ["freshness"] as const,
};

export function useJournals(params: JournalSearchParams) {
  return useQuery({
    queryKey: qk.journals(params),
    queryFn: () => apiGet<JournalSearchResponse>("/journals", { ...params }),
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
