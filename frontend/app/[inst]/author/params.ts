import type { AuthorFetchOptions, AuthorSearchFilters, AuthorSearchSort } from "@/lib/api";

/** Page sizes the pager offers; 50 is the default. */
const PAGE_SIZES = [25, 50, 100];

/** Valid sort values; mirrors the sort select in page-client. */
const SORTS: AuthorSearchSort[] = ["works_desc", "name_asc", "name_desc", "last_pub_desc"];

/** Everything the author directory derives from the URL, plus the exact
 * arguments its `useAuthorDirectory` hook needs. */
export type AuthorDirectoryParams = {
  /** URL query, "" when absent. */
  q: string;
  /** Fetch query: `q`, undefined when empty. */
  query: string | undefined;
  hasOrcid: "yes" | "no" | null;
  selected: {
    faculty: string[];
    org: string[];
    works: string[];
    last_pub: string[];
    topic: string[];
  };
  sort: AuthorSearchSort;
  pageSize: number;
  offset: number;
  filters: AuthorSearchFilters;
  opts: AuthorFetchOptions;
};

/** Pipe-joined multi-select param → list of values. */
function paramValues(sp: { get(key: string): string | null }, key: string): string[] {
  return (sp.get(key) ?? "").split("|").filter(Boolean);
}

/**
 * URL → author-directory state, shared by the client view and the server
 * page so the seeded React Query key matches the key the hook computes on
 * first render. Years carry the global year lens; the server and the first
 * client render both pass none, because the stored selection loads after
 * mount.
 */
export function authorDirectoryParams(
  sp: { get(key: string): string | null },
  years: { year_from?: number; year_to?: number } = {},
): AuthorDirectoryParams {
  const q = sp.get("q") ?? "";
  const orcidParam = sp.get("has_orcid");
  const hasOrcid: "yes" | "no" | null =
    orcidParam === "yes" || orcidParam === "no" ? orcidParam : null;
  // Facet selections mirror the journal search's URL style: pipe-joined
  // values per multi-select param, plus one single-select yes/no group.
  const selected = {
    faculty: paramValues(sp, "faculty"),
    org: paramValues(sp, "org"),
    works: paramValues(sp, "works"),
    last_pub: paramValues(sp, "last_pub"),
    topic: paramValues(sp, "topic"),
  };
  // Sort and paging are URL state too; defaults stay out of the params.
  const sortParam = sp.get("sort");
  const sort: AuthorSearchSort = SORTS.some((s) => s === sortParam)
    ? (sortParam as AuthorSearchSort)
    : "works_desc";
  const limitParam = parseInt(sp.get("limit") ?? "", 10);
  const pageSize = PAGE_SIZES.includes(limitParam) ? limitParam : 50;
  const offsetParam = parseInt(sp.get("offset") ?? "", 10);
  const offset = Number.isFinite(offsetParam) && offsetParam > 0 ? offsetParam : 0;

  const filters: AuthorSearchFilters = {
    faculty: selected.faculty.length > 0 ? selected.faculty : undefined,
    org: selected.org.length > 0 ? selected.org : undefined,
    works: selected.works.length > 0 ? selected.works : undefined,
    last_pub: selected.last_pub.length > 0 ? selected.last_pub : undefined,
    topic: selected.topic.length > 0 ? selected.topic : undefined,
    has_orcid: hasOrcid ?? undefined,
  };

  return {
    q,
    query: q || undefined,
    hasOrcid,
    selected,
    sort,
    pageSize,
    offset,
    filters,
    opts: {
      sort: sort === "works_desc" ? undefined : sort,
      offset: offset > 0 ? offset : undefined,
      limit: pageSize === 50 ? undefined : pageSize,
      year_from: years.year_from,
      year_to: years.year_to,
    },
  };
}
