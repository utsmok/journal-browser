import type { OrgUnitLevel, OrgUnitSearchParams, OrgUnitSearchSort } from "@/lib/api";

/** Page sizes the pager offers; 50 is the default. */
const PAGE_SIZES = [25, 50, 100];

/** Valid sort values; the backend default is relevance-with-q, else works desc. */
const SORTS: OrgUnitSearchSort[] = ["relevance", "name", "authors", "works", "deal_works"];

/** Everything the org-unit directory derives from the URL, plus the exact
 * argument its `useOrgUnits` hook needs. */
export type OrgUnitDirectoryParams = {
  /** URL query, "" when absent. */
  q: string;
  /** Fetch query: `q`, undefined when empty. */
  query: string | undefined;
  level: OrgUnitLevel;
  faculty: string[];
  works: string[];
  usesDeals: boolean;
  sort: OrgUnitSearchSort | undefined;
  dir: "asc" | "desc" | null;
  pageSize: number;
  offset: number;
  /** Exact argument for useOrgUnits (and its React Query key). */
  request: OrgUnitSearchParams;
};

/** Pipe-joined multi-select param → list of values. */
function paramValues(sp: { get(key: string): string | null }, key: string): string[] {
  return (sp.get(key) ?? "").split("|").filter(Boolean);
}

/**
 * URL → org-unit directory state, shared by the client view and the server
 * page so the seeded React Query key matches the key the hook computes on
 * first render. Years carry the global year lens; the server and the first
 * client render both pass none, because the stored selection loads after
 * mount.
 */
export function orgUnitDirectoryParams(
  sp: { get(key: string): string | null },
  years: { year_from?: number; year_to?: number } = {},
): OrgUnitDirectoryParams {
  const q = sp.get("q") ?? "";
  const levelParam = sp.get("level");
  const level: OrgUnitLevel =
    levelParam === "group" || levelParam === "institute" ? levelParam : "faculty";
  const faculty = paramValues(sp, "faculty");
  const works = paramValues(sp, "works");
  const usesDeals = sp.get("uses_deals") === "true";
  const sortParam = sp.get("sort");
  const sort: OrgUnitSearchSort | undefined = SORTS.includes(sortParam as OrgUnitSearchSort)
    ? (sortParam as OrgUnitSearchSort)
    : undefined;
  const dirParam = sp.get("dir");
  const dir: "asc" | "desc" | null = dirParam === "asc" || dirParam === "desc" ? dirParam : null;
  const limitParam = parseInt(sp.get("limit") ?? "", 10);
  const pageSize = PAGE_SIZES.includes(limitParam) ? limitParam : 50;
  const offsetParam = parseInt(sp.get("offset") ?? "", 10);
  const offset = Number.isFinite(offsetParam) && offsetParam > 0 ? offsetParam : 0;

  return {
    q,
    query: q || undefined,
    level,
    faculty,
    works,
    usesDeals,
    sort,
    dir,
    pageSize,
    offset,
    request: {
      level,
      q: q || undefined,
      faculty: faculty.length > 0 ? faculty : undefined,
      works: works.length > 0 ? works : undefined,
      uses_deals: usesDeals || undefined,
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
