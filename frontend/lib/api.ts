import type { components } from "./api-types";
import { trackApiError, trackSearch } from "./usage/tracker";

type Schemas = components["schemas"];

export type JournalListItem = Schemas["JournalListItem"];

export type DealLink = Schemas["DealLinkOut"];

export type DealOut = Schemas["DealOut"];

export type JournalDetailResponse = Schemas["JournalDetailResponse"];

export type JournalSearchResponse = Schemas["JournalSearchResponse"];

/** Three similar-journal cuts: institution-publishing venues, deal-covered venues, and the general list. */
export type SimilarJournalsBundle = Schemas["SimilarJournalsBundle"];

export type OpenalexTopic = Schemas["OpenalexTopicOut"];

export type OpenalexSource = Schemas["OpenalexInfo"];

/** Institution work metrics computed from OpenAlex works. */
export type InstitutionMetrics = Schemas["InstitutionMetrics"];

export type WorksPage = Schemas["WorksPage"];

export type LimitationOut = Schemas["LimitationOut"];
export type FreshnessResponse = Schemas["FreshnessResponse"];
export type StatsYear = Schemas["StatsYear"];
export type FunderListItem = Schemas["FunderListItem"];
export type FunderSearchResponse = Schemas["FunderSearchResponse"];
export type FunderDetailResponse = Schemas["FunderDetailResponse"];
export type FunderFitOut = Schemas["FunderFitOut"];
export type Attribution = Schemas["Attribution"];

// --- Author profiles (Pure-based, per institution) ---

export type AuthorSearchItem = Schemas["AuthorItem"];

export type AuthorFacetBucket = Schemas["AuthorFacet"];

/** Author search ordering; the backend default is works_desc. */
export type AuthorSearchSort = "works_desc" | "name_asc" | "name_desc" | "last_pub_desc";

export type AuthorSearchResponse = Schemas["AuthorSearchResponse"];

/** Sort, paging, and publication-year options for fetchAuthors. */
export type AuthorFetchOptions = {
  sort?: AuthorSearchSort;
  offset?: number;
  limit?: number;
  /** Publication-year range (global year lens; server clamps to the data window). */
  year_from?: number;
  year_to?: number;
};

/** Author search facet filters; arrays are comma-joined in the query string. */
export type AuthorSearchFilters = {
  faculty?: string[];
  org?: string[];
  has_orcid?: "yes" | "no";
  /** Publication-count strata: "1-4" | "5-19" | "20-49" | "50+". */
  works?: string[];
  /** Recency buckets: "2025-2026" | "2022-2024" | "2020-2021" | "none". */
  last_pub?: string[];
  topic?: string[];
};

export type AuthorSimilarJournal = Schemas["AuthorSimilarJournal"];

/** Roster author matched on a gap work's OpenAlex authorships. */
export type UtAuthorAttribution = Schemas["UtAuthorAttribution"];

export type AuthorProfile = Schemas["AuthorProfileResponse"];

export type SortKey =
  | "relevance"
  | "title"
  | "publisher"
  | "institution_works"
  | "quartile"
  | "topic"
  | "apc"
  | "2yr_mean_citedness";

export type SearchIn = "all" | "title" | "publisher" | "topic";

/** Publication-year range params accepted by the works/profile/detail/CSV
 * endpoints; the global year lens feeds these. */
export type YearParams = { year_from?: number; year_to?: number };

export type JournalSearchParams = {
  q?: string;
  search_in?: SearchIn;
  deal?: "any" | "covered" | "not_covered";
  oa?: boolean;
  doaj?: boolean;
  quartile?: string;
  publisher?: string;
  has_apc?: boolean;
  has_works?: boolean;
  topic?: string;
  /** Comma-separated multi-select, OR'd server-side. */
  oa_type?: string;
  /** OpenAlex venue type filter: "journal", "book series", ... */
  pub_type?: string;
  /** Modal journal language, comma-separated ISO 639-1 codes ("en"). */
  language?: string;
  /** Self-archiving route per Jisc: "submitted" | "accepted" | "published" | "none". */
  green_oa?: string;
  /** Jisc OPF funder id; annotates rows with funder_fit. */
  funder?: number;
  /** Funder-fit tier filter; needs `funder` set. */
  funder_fit?: string;
  /** Publication-year range start (global year lens; server clamps to the data window). */
  year_from?: number;
  /** Publication-year range end (global year lens; server clamps to the data window). */
  year_to?: number;
  sort?: SortKey;
  /** Sort direction; omitted = each key's natural direction. */
  dir?: "asc" | "desc";
  cursor?: string;
  limit?: number;
  include_facets?: boolean;
};

/** Error with an HTTP status; message stays technical (console only). */
class ApiError extends Error {
  status: number;
  constructor(status: number, path: string) {
    super(`API ${status} on ${path}`);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * Human copy for fetch failures; the raw error is already in the console
 * (apiGet logs it). Maps the statuses the UI can actually hit.
 */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 400 || err.status === 422)
      return "The request was not valid. Adjust the filters and try again.";
    if (err.status === 404)
      return "We could not find that information. Check the address, or go back and adjust your search.";
    if (err.status >= 500) return "The server could not process the search. Try again in a moment.";
  }
  return "Something went wrong while loading this data. Try again in a moment.";
}

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
  try {
    const res = await fetch(`/api/v1${path}${qs ? `?${qs}` : ""}`, {
      cache: "no-store",
    });
    if (!res.ok) {
      console.error(`API ${res.status} on ${path}`);
      trackApiError("GET", path, res.status);
      throw new ApiError(res.status, path);
    }
    return (await res.json()) as T;
  } catch (err) {
    if (!(err instanceof ApiError)) console.error(`Fetch failed on ${path}`, err);
    throw err;
  }
}

export async function fetchAuthors(
  inst: string,
  q?: string,
  filters: AuthorSearchFilters = {},
  opts: AuthorFetchOptions = {},
): Promise<AuthorSearchResponse> {
  const data = await apiGet<AuthorSearchResponse>(`/${inst}/authors`, {
    q,
    limit: opts.limit,
    faculty: filters.faculty?.join("|"),
    org: filters.org?.join("|"),
    has_orcid: filters.has_orcid,
    works: filters.works?.join("|"),
    last_pub: filters.last_pub?.join("|"),
    topic: filters.topic?.join("|"),
    sort: opts.sort,
    offset: opts.offset,
    year_from: opts.year_from,
    year_to: opts.year_to,
  });
  trackSearch({
    query: q ?? "",
    results_count: data.total,
    search_scope: "authors",
    filters: Object.keys(filters).length ? { ...filters } : undefined,
  });
  return data;
}

export async function fetchAuthor(
  inst: string,
  pureUuid: string,
  years?: YearParams,
): Promise<AuthorProfile> {
  return apiGet<AuthorProfile>(`/${inst}/authors/${encodeURIComponent(pureUuid)}`, {
    year_from: years?.year_from,
    year_to: years?.year_to,
  });
}

// --- Publishers + org units (browse facets) ---

export type OaTypeCounts = Partial<
  Record<"gold" | "diamond" | "generic" | "hybrid" | "subscription", number>
>;

export type PublisherListItem = Schemas["PublisherListItem"];

export type PublisherSearchResponse = Schemas["PublisherSearchResponse"];

export type DealDiscrepancy = Schemas["DealDiscrepancyRow"];

export type PublisherDetailResponse = Schemas["PublisherDetailResponse"];

export type PublisherSearchSort = "relevance" | "name" | "journals" | "works" | "deals" | "apc";

/** List params for the publisher surface; arrays are pipe-joined in the query. */
export type PublisherSearchParams = {
  q?: string;
  oa_type?: string[];
  deal?: "covered" | "none";
  quartile?: string[];
  topic?: string;
  size?: string[];
  has_apc?: boolean;
  has_works?: boolean;
  sort?: PublisherSearchSort;
  dir?: "asc" | "desc";
  offset?: number;
  limit?: number;
  include_facets?: boolean;
};

/** Org-unit hierarchy level; institutes (MESA+, TechMed, DSI) are their
 * own level, separate from faculties and research groups. */
export type OrgUnitLevel = "faculty" | "group" | "institute";

export type OrgUnitItem = Schemas["OrgUnitItem"];

export type OrgUnitSearchResponse = Schemas["OrgUnitSearchResponse"];

export type OrgUnitDetailResponse = Schemas["OrgUnitDetailResponse"];

export type OrgUnitSearchSort = "relevance" | "name" | "authors" | "works" | "deal_works";

export type OrgUnitSearchParams = {
  level?: OrgUnitLevel;
  q?: string;
  faculty?: string[];
  /** Works strata on n_works: "1-4" | "5-19" | "20-49" | "50+". */
  works?: string[];
  uses_deals?: boolean;
  sort?: OrgUnitSearchSort;
  dir?: "asc" | "desc";
  offset?: number;
  limit?: number;
  include_facets?: boolean;
};

/** Unit names contain spaces, commas, "&" and "/": encode each segment,
 * keep "/" so the backend {name:path} route still resolves. */
export function encodeNamePath(name: string): string {
  return name.split("/").map(encodeURIComponent).join("/");
}

/** Usage filter dump for directory fetchers: paging keys stripped. */
function usageDirectoryFilters(params: object): Record<string, unknown> | undefined {
  const {
    q: _q,
    sort: _sort,
    dir: _dir,
    offset: _offset,
    limit: _limit,
    include_facets: _include_facets,
    ...rest
  } = params as Record<string, unknown>;
  return Object.keys(rest).length ? rest : undefined;
}

export async function fetchPublishers(
  inst: string,
  params: PublisherSearchParams = {},
): Promise<PublisherSearchResponse> {
  const data = await apiGet<PublisherSearchResponse>(`/${inst}/publishers`, {
    q: params.q,
    oa_type: params.oa_type?.join("|"),
    deal: params.deal,
    quartile: params.quartile?.join("|"),
    topic: params.topic,
    size: params.size?.join("|"),
    // String(false) must survive: false is a meaningful filter value.
    has_apc: params.has_apc === undefined ? undefined : String(params.has_apc),
    has_works: params.has_works === undefined ? undefined : String(params.has_works),
    sort: params.sort,
    dir: params.dir,
    offset: params.offset,
    limit: params.limit,
    include_facets: params.include_facets ? "true" : undefined,
  });
  trackSearch({
    query: params.q ?? "",
    results_count: data.total,
    search_scope: "publishers",
    filters: usageDirectoryFilters(params),
  });
  return data;
}

export async function fetchPublisher(
  inst: string,
  name: string,
  years?: YearParams,
): Promise<PublisherDetailResponse> {
  return apiGet<PublisherDetailResponse>(`/${inst}/publishers/${encodeNamePath(name)}`, {
    year_from: years?.year_from,
    year_to: years?.year_to,
  });
}

export async function fetchOrgUnits(
  inst: string,
  params: OrgUnitSearchParams = {},
): Promise<OrgUnitSearchResponse> {
  const data = await apiGet<OrgUnitSearchResponse>(`/${inst}/orgunits`, {
    level: params.level,
    q: params.q,
    faculty: params.faculty?.join("|"),
    works: params.works?.join("|"),
    uses_deals: params.uses_deals ? "true" : undefined,
    sort: params.sort,
    dir: params.dir,
    offset: params.offset,
    limit: params.limit,
    include_facets: params.include_facets ? "true" : undefined,
  });
  trackSearch({
    query: params.q ?? "",
    results_count: data.total,
    search_scope: "orgunits",
    filters: usageDirectoryFilters(params),
  });
  return data;
}

export async function fetchOrgUnit(
  inst: string,
  level: OrgUnitLevel,
  name: string,
  years?: YearParams,
): Promise<OrgUnitDetailResponse> {
  return apiGet<OrgUnitDetailResponse>(`/${inst}/orgunits/${level}/${encodeNamePath(name)}`, {
    year_from: years?.year_from,
    year_to: years?.year_to,
  });
}
