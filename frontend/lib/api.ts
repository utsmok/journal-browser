import type { components } from "./api-types";

type Schemas = components["schemas"];

/**
 * The generated types trail the backend contract (api-types.ts is
 * auto-generated). Fields the updated backend adds are declared here so the
 * frontend can code against them while the old backend simply omits them.
 */
export type JournalListItem = Schemas["JournalListItem"] & {
  /** Display APC: OpenAlex list price when known, else the OpenAPC range. */
  apc_source?: "openalex" | "openapc" | null;
  apc_price?: number | null;
  apc_currency?: string | null;
  apc_low?: number | null;
  apc_high?: number | null;
  apc_stats?: {
    period: number;
    article_count: number;
    euro_min: number | null;
    euro_max: number | null;
    euro_mean: number | null;
  }[];
  oa_type?: ("gold" | "diamond" | "hybrid" | "subscription") | null;
  primary_topic?: string | null;
};

export type DealLink = {
  url?: string | null;
  text?: string | null;
  category?: string | null;
};

export type DealOut = Omit<Schemas["DealOut"], "links"> & {
  links?: DealLink[] | null;
};

export type JournalDetailResponse = Schemas["JournalDetailResponse"] & {
  journal: JournalListItem;
  openalex?: OpenalexSource | null;
  openaire?: { matched_works: number } | null;
  institution_metrics?: InstitutionMetrics | null;
};

export type JournalSearchResponse = Schemas["JournalSearchResponse"];

type SimilarJournal = {
  issn_l: string;
  title: string | null;
  publisher_name: string | null;
  quartile?: string | null;
  is_oa?: boolean | null;
  deal_covered: boolean;
  works: number;
  shared_topics: number;
  similarity?: number | null;
};

/** Three similar-journal cuts: institution-publishing venues, deal-covered venues, and the general list. */
export type SimilarJournalsBundle = {
  institution: SimilarJournal[];
  deals: SimilarJournal[];
  all: SimilarJournal[];
};

/** OpenAlex source record for a journal (absent on old backends). */
export type OpenalexTopic = {
  id: string;
  display_name: string;
  count: number;
  score?: number;
  subfield?: { id?: string; display_name?: string } | null;
  field?: { id?: string; display_name?: string } | null;
  domain?: { id?: string; display_name?: string } | null;
};

export type OpenalexSource = {
  id?: string | null;
  url?: string | null;
  cited_by_count?: number | null;
  works_count?: number | null;
  host_organization_name?: string | null;
  first_publication_year?: number | null;
  last_publication_year?: number | null;
  topics?: OpenalexTopic[];
};

/** Institution work metrics computed from OpenAlex works. */
export type InstitutionMetrics = {
  openalex_matched: number;
  fwci_avg: number | null;
  fwci_n: number;
  retracted: number;
  cited_total: number;
  // Canonical-store-grounded totals; null when that store is unreachable.
  canonical_total?: number | null;
  canonical_retracted?: number | null;
  canonical_oa?: {
    gold?: number;
    hybrid?: number;
    green?: number;
    bronze?: number;
    diamond?: number;
    closed?: number;
    unknown?: number;
  } | null;
};

type JournalWork = {
  id: string;
  url: string | null;
  doi: string | null;
  title: string | null;
  year: number | null;
  oa_status: string | null;
  fwci: number | null;
  cited_by_count: number;
  is_retracted: boolean | null;
  type: string | null;
  // ut-metadata provenance: canonical work type + OpenAlex works_stats backing.
  work_type?: string | null;
  in_openalex?: boolean | null;
};

export type WorksPage = {
  items: JournalWork[];
  total: number;
  page: number;
  page_size: number;
};

export type LimitationOut = Schemas["LimitationOut"];
export type FreshnessResponse = Schemas["FreshnessResponse"];
export type StatsYear = Schemas["StatsYear"];
export type Attribution = Schemas["Attribution"];

// --- Author profiles (Pure-based, per institution) ---

export type AuthorSearchItem = {
  pure_uuid: string;
  name: string;
  faculty: string | null;
  research_group: string | null;
  n_works: number;
  orcid: string | null;
  /** Affiliation confirmed in Pure; unconfirmed authors are hidden by default. */
  confirmed: boolean;
  last_pub_year: number | null;
  primary_topic: string | null;
};

export type AuthorFacetBucket = { value: string; count: number };

/** Facet counts for the author search; every list is sorted by count desc. */
export type AuthorSearchFacets = {
  faculty: AuthorFacetBucket[];
  org: AuthorFacetBucket[];
  works: AuthorFacetBucket[];
  last_pub: AuthorFacetBucket[];
  topic: AuthorFacetBucket[];
};

/** Author search ordering; the backend default is works_desc. */
export type AuthorSearchSort =
  | "works_desc"
  | "name_asc"
  | "name_desc"
  | "last_pub_desc";

export type AuthorSearchResponse = {
  /** False when this institution has no author data at all (e.g. /rug/author). */
  enabled: boolean;
  /** Unpaginated filtered count. */
  total: number;
  items: AuthorSearchItem[];
  facets?: AuthorSearchFacets;
  /** Echoes the requested sort. */
  sort?: AuthorSearchSort;
  /** Echoes the requested page offset. */
  offset?: number;
};

/** Sort and paging options for fetchAuthors. */
export type AuthorFetchOptions = {
  sort?: AuthorSearchSort;
  offset?: number;
  limit?: number;
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

export type AuthorSimilarJournal = {
  issn_l: string;
  title: string | null;
  /** Similarity (1 - cosine distance); higher is more similar. */
  score: number;
  oa_type: "gold" | "diamond" | "hybrid" | "subscription";
  deal_covered: boolean;
};

export type AuthorProfile = {
  author: {
    pure_uuid: string;
    name: string;
    orcid: string | null;
    openalex_author_id: string | null;
    openaire_person_id: string | null;
    crossref_orcid: string | null;
    faculty: string | null;
    research_group: string | null;
    orgs: string[];
    n_works: number;
  };
  /** Per-year OA counts for the author's works, sorted year descending. */
  oa_by_year: {
    year: number;
    total: number;
    gold: number;
    green: number;
    hybrid: number;
    bronze: number;
    closed: number;
  }[];
  journals: {
    issn_l: string;
    title: string | null;
    n_works: number;
    oa_type: "gold" | "diamond" | "hybrid" | "subscription";
  }[];
  topics: { name: string; n: number }[];
  similar: {
    all: AuthorSimilarJournal[];
    deals: AuthorSimilarJournal[];
    diamond: AuthorSimilarJournal[];
  };
  /** The author's hybrid/subscription journals with diamond/deal alternatives. */
  alternatives: {
    issn_l: string;
    title: string | null;
    n_works: number;
    options: AuthorSimilarJournal[];
  }[];
  /** Most recent works, year descending, capped at 200. */
  works: {
    pure_uuid: string;
    title: string;
    year: number;
    doi: string | null;
    oa_status: string | null;
    journal_issn_l: string | null;
    journal_title: string | null;
  }[];
};

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
    if (err.status === 400)
      return "The request was not valid. Adjust the filters and try again.";
    if (err.status === 404) return "We could not find that information.";
    if (err.status >= 500)
      return "The server could not process the search. Try again in a moment.";
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
  return apiGet<AuthorSearchResponse>(`/${inst}/authors`, {
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
  });
}

export async function fetchAuthor(
  inst: string,
  pureUuid: string,
): Promise<AuthorProfile> {
  return apiGet<AuthorProfile>(`/${inst}/authors/${encodeURIComponent(pureUuid)}`);
}
