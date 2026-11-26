import type { PublisherSearchParams, PublisherSearchSort, YearParams } from "@/lib/api";

const PAGE_SIZES = [25, 50, 100];

const SORTS: readonly PublisherSearchSort[] = [
  "relevance",
  "name",
  "journals",
  "works",
  "deals",
  "apc",
];

/** Publisher deal filter: accept legacy "none" URLs, send the canonical value. */
export function normalizeDeal(value: string): "covered" | "not_covered" | null {
  if (value === "covered" || value === "not_covered") return value;
  if (value === "none") return "not_covered";
  return null;
}

/** Parsed URL state of the publisher route plus the list params the
 * usePublishers query runs under. */
export type PublisherDirectoryState = {
  q: string;
  oaTypes: string[];
  deal: "covered" | "not_covered" | null;
  quartiles: string[];
  sizes: string[];
  topic: string;
  hasApc: "yes" | "no" | null;
  hasWorks: "true" | "false" | null;
  sort: PublisherSearchSort | undefined;
  dir: "asc" | "desc" | null;
  pageSize: number;
  offset: number;
  /** Exactly the object the page passes to usePublishers. */
  params: PublisherSearchParams;
};

/** Pipe-joined multi-select param → list of values. */
function paramValues(sp: { get(key: string): string | null }, key: string): string[] {
  return (sp.get(key) ?? "").split("|").filter(Boolean);
}

/**
 * URL of the publisher route → directory state and list params. The client
 * page feeds it useSearchParams, the server page the awaited searchParams,
 * so both compute the same React Query key. `years` carries the global year
 * lens, which hydrates from localStorage after mount; the first render on
 * both sides runs over the full data window, so the server seeds with the
 * empty range.
 */
export function publisherDirectoryParams(
  sp: { get(key: string): string | null },
  years: YearParams = {},
): PublisherDirectoryState {
  const q = sp.get("q") ?? "";
  const oaTypes = paramValues(sp, "oa_type");
  const dealParam = sp.get("deal");
  const deal = dealParam ? normalizeDeal(dealParam) : null;
  const quartiles = paramValues(sp, "quartile");
  const sizes = paramValues(sp, "size");
  const topic = sp.get("topic") ?? "";
  const apcParam = sp.get("has_apc");
  const hasApc: "yes" | "no" | null = apcParam === "yes" || apcParam === "no" ? apcParam : null;
  const worksParam = sp.get("has_works");
  const hasWorks: "true" | "false" | null =
    worksParam === "true" || worksParam === "false" ? worksParam : null;
  // The backend default is relevance-with-q, else works desc.
  const sortParam = sp.get("sort");
  const sort = SORTS.find((candidate) => candidate === sortParam);
  const dirParam = sp.get("dir");
  const dir: "asc" | "desc" | null = dirParam === "asc" || dirParam === "desc" ? dirParam : null;
  const limitParam = parseInt(sp.get("limit") ?? "", 10);
  const pageSize = PAGE_SIZES.includes(limitParam) ? limitParam : 50;
  const offsetParam = parseInt(sp.get("offset") ?? "", 10);
  const offset = Number.isFinite(offsetParam) && offsetParam > 0 ? offsetParam : 0;

  return {
    q,
    oaTypes,
    deal,
    quartiles,
    sizes,
    topic,
    hasApc,
    hasWorks,
    sort,
    dir,
    pageSize,
    offset,
    params: {
      q: q || undefined,
      oa_type: oaTypes.length > 0 ? oaTypes : undefined,
      deal: deal ?? undefined,
      quartile: quartiles.length > 0 ? quartiles : undefined,
      size: sizes.length > 0 ? sizes : undefined,
      topic: topic || undefined,
      has_apc: hasApc === null ? undefined : hasApc === "yes",
      has_works: hasWorks === null ? undefined : hasWorks === "true",
      sort,
      dir: dir ?? undefined,
      offset: offset > 0 ? offset : undefined,
      limit: pageSize === 50 ? undefined : pageSize,
      include_facets: true,
      year_from: years.year_from,
      year_to: years.year_to,
    },
  };
}
