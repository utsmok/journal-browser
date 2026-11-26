import type { FunderSearchParams, FunderSearchSort, YearParams } from "@/lib/api";

const PAGE_SIZES = [25, 50, 100];

/** Parsed URL state of the funders route plus the list params the
 * useFunderDirectory query runs under. */
export type FunderDirectoryState = {
  q: string;
  countries: string[];
  hasWorksParam: string | null;
  hasWorks: boolean | undefined;
  oaPub: string[];
  greenArch: string[];
  dataPolicy: string[];
  policyParam: string | null;
  policyStructured: boolean | undefined;
  sort: FunderSearchSort | undefined;
  dir: "asc" | "desc" | null;
  pageSize: number;
  offset: number;
  /** Exactly the object the page passes to useFunderDirectory. */
  params: FunderSearchParams;
};

/** Pipe-joined multi-select param → list of values. */
function paramValues(sp: { get(key: string): string | null }, key: string): string[] {
  return (sp.get(key) ?? "").split("|").filter(Boolean);
}

/**
 * URL of the funders route → directory state and list params. The client
 * page feeds it useSearchParams, the server page the awaited searchParams,
 * so both compute the same React Query key. `years` carries the global year
 * lens, which hydrates from localStorage after mount; the first render on
 * both sides runs over the full data window, so the server seeds with the
 * empty range.
 */
export function funderDirectoryParams(
  sp: { get(key: string): string | null },
  years: YearParams = {},
): FunderDirectoryState {
  const q = sp.get("q") ?? "";
  const countries = paramValues(sp, "country");
  const hasWorksParam = sp.get("has_works");
  const hasWorks = hasWorksParam === "true" ? true : hasWorksParam === "false" ? false : undefined;
  const oaPub = paramValues(sp, "oa_publishing");
  const greenArch = paramValues(sp, "green_archiving");
  const dataPolicy = paramValues(sp, "data_policy");
  const policyParam = sp.get("policy_structured");
  const policyStructured =
    policyParam === "true" ? true : policyParam === "false" ? false : undefined;
  const sortParam = sp.get("sort");
  const sort: FunderSearchSort | undefined =
    sortParam === "works" || sortParam === "name" ? sortParam : undefined;
  const dirParam = sp.get("dir");
  const dir: "asc" | "desc" | null = dirParam === "asc" || dirParam === "desc" ? dirParam : null;
  const limitParam = parseInt(sp.get("limit") ?? "", 10);
  const pageSize = PAGE_SIZES.includes(limitParam) ? limitParam : 50;
  const offsetParam = parseInt(sp.get("offset") ?? "", 10);
  const offset = Number.isFinite(offsetParam) && offsetParam > 0 ? offsetParam : 0;

  return {
    q,
    countries,
    hasWorksParam,
    hasWorks,
    oaPub,
    greenArch,
    dataPolicy,
    policyParam,
    policyStructured,
    sort,
    dir,
    pageSize,
    offset,
    params: {
      q: q || undefined,
      country: countries.length > 0 ? countries : undefined,
      policy_structured: policyStructured,
      has_works: hasWorks,
      oa_publishing: oaPub.length > 0 ? oaPub : undefined,
      green_archiving: greenArch.length > 0 ? greenArch : undefined,
      data_policy: dataPolicy.length > 0 ? dataPolicy : undefined,
      sort,
      dir: dir ?? undefined,
      offset,
      limit: pageSize,
      year_from: years.year_from,
      year_to: years.year_to,
    },
  };
}
