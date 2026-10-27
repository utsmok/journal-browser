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
  publisher_canonical?: string | null;
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

// --- Publishers + org units (browse facets) ---

export type OaTypeCounts = Partial<
  Record<"gold" | "diamond" | "hybrid" | "subscription", number>
>;

export type PublisherListItem = {
  name: string;
  n_journals: number;
  n_works: number;
  /** Journals covered by an open access deal. */
  deal_journals: number;
  oa_types: OaTypeCounts;
  quartiles: Partial<Record<"q1" | "q2" | "q3" | "q4" | "none", number>>;
  apc: { n_journals: number; eur_min: number | null; eur_max: number | null };
  topics: { name: string; n: number }[];
};

export type PublisherFacets = {
  oa_type: Record<string, number>;
  deal: Record<string, number>;
  quartile: Record<string, number>;
  has_apc: Record<string, number>;
  size: Record<string, number>;
  topic: Record<string, number>;
};

export type PublisherSearchResponse = {
  total: number;
  items: PublisherListItem[];
  facets?: PublisherFacets;
};

export type DealDiscrepancy = Schemas["DealDiscrepancyRow"];

export type PublisherDetailResponse = {
  publisher: PublisherListItem;
  journals: JournalListItem[];
  deals: DealOut[];
  deal_discrepancies: DealDiscrepancy[];
  n_discrepancies: number;
  works_by_year: StatsYear[];
};

export type PublisherSearchSort =
  | "relevance"
  | "name"
  | "journals"
  | "works"
  | "deals"
  | "apc";

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

/** Org-unit hierarchy level; a unit is a faculty or a research group. */
export type OrgUnitLevel = "faculty" | "group";

export type OrgUnitItem = {
  level: OrgUnitLevel;
  name: string;
  /** Parent faculty; set on group level only. */
  faculty: string | null;
  n_authors: number;
  n_works: number;
  /** Child research groups; faculty level only. */
  n_groups: number | null;
  deal_works: number;
  apc_euro_total: number;
  apc_n: number;
  topics: { name: string; n: number }[];
};

export type OrgUnitSearchResponse = {
  level: OrgUnitLevel;
  total: number;
  items: OrgUnitItem[];
  facets?: {
    faculty?: Record<string, number>;
    size: Record<string, number>;
    uses_deals: Record<string, number>;
  };
};

export type OrgUnitDetailResponse = {
  unit: OrgUnitItem;
  groups: OrgUnitItem[] | null;
  journals: {
    issn_l: string;
    title: string | null;
    n_works: number;
    deal_covered: boolean;
    oa_type: "gold" | "diamond" | "hybrid" | "subscription";
    quartile: string | null;
  }[];
  authors: {
    pure_uuid: string;
    name: string;
    n_works: number;
    orcid: string | null;
    primary_topic: string | null;
  }[];
  works_by_year: StatsYear[];
  deal_usage: { label: string; n_works: number; euro: number }[];
};

export type OrgUnitSearchSort =
  | "relevance"
  | "name"
  | "authors"
  | "works"
  | "deal_works";

export type OrgUnitSearchParams = {
  level?: OrgUnitLevel;
  q?: string;
  faculty?: string[];
  /** Works strata on n_works: "1-4" | "5-19" | "20-49" | "50+". */
  works?: string[];
  uses_deals?: boolean;
  sort?: OrgUnitSearchSort;
  offset?: number;
  limit?: number;
  include_facets?: boolean;
};

/** Unit names contain spaces, commas, "&" and "/": encode each segment,
 * keep "/" so the backend {name:path} route still resolves. */
export function encodeNamePath(name: string): string {
  return name.split("/").map(encodeURIComponent).join("/");
}

export async function fetchPublishers(
  inst: string,
  params: PublisherSearchParams = {},
): Promise<PublisherSearchResponse> {
  return apiGet<PublisherSearchResponse>(`/${inst}/publishers`, {
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
}

export async function fetchPublisher(
  inst: string,
  name: string,
): Promise<PublisherDetailResponse> {
  return apiGet<PublisherDetailResponse>(
    `/${inst}/publishers/${encodeNamePath(name)}`,
  );
}

export async function fetchOrgUnits(
  inst: string,
  params: OrgUnitSearchParams = {},
): Promise<OrgUnitSearchResponse> {
  return apiGet<OrgUnitSearchResponse>(`/${inst}/orgunits`, {
    level: params.level,
    q: params.q,
    faculty: params.faculty?.join("|"),
    works: params.works?.join("|"),
    uses_deals: params.uses_deals ? "true" : undefined,
    sort: params.sort,
    offset: params.offset,
    limit: params.limit,
    include_facets: params.include_facets ? "true" : undefined,
  });
}

export async function fetchOrgUnit(
  inst: string,
  level: OrgUnitLevel,
  name: string,
): Promise<OrgUnitDetailResponse> {
  return apiGet<OrgUnitDetailResponse>(
    `/${inst}/orgunits/${level}/${encodeNamePath(name)}`,
  );
}
