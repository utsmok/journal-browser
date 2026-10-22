import type { components } from "./api-types";

export type Schemas = components["schemas"];
export type JournalListItem = Schemas["JournalListItem"];
export type JournalSearchResponse = Schemas["JournalSearchResponse"];
export type JournalDetailResponse = Schemas["JournalDetailResponse"];
export type DealOut = Schemas["DealOut"];
export type LimitationOut = Schemas["LimitationOut"];
export type FreshnessResponse = Schemas["FreshnessResponse"];
export type FreshnessEntry = Schemas["FreshnessEntry"];
export type StatsYear = Schemas["StatsYear"];
export type ScimagojrOut = Schemas["ScimagojrOut"];
export type ApcAggregateOut = Schemas["ApcAggregateOut"];
export type ApcEvidenceOut = Schemas["ApcEvidenceOut"];
export type Attribution = Schemas["Attribution"];

export type SortKey =
  | "relevance"
  | "title"
  | "institution_works"
  | "2yr_mean_citedness";

export type JournalSearchParams = {
  q?: string;
  deal?: "any" | "covered" | "not_covered";
  oa?: boolean;
  doaj?: boolean;
  quartile?: string;
  topic?: string;
  sort?: SortKey;
  cursor?: string;
  limit?: number;
};

/** GET helper against the same-origin /api proxy (next.config.mjs rewrites). */
export async function apiGet<T>(
  path: string,
  params?: Record<string, string | number | boolean | undefined | null>,
): Promise<T> {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const qs = search.toString();
  const res = await fetch(`/api/v1${path}${qs ? `?${qs}` : ""}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`API ${res.status} on ${path}`);
  return (await res.json()) as T;
}
