import type { components, operations } from "./api-types";
import type { LabelT } from "./work-type";
import { trackApiError } from "./usage/tracker";

type Schemas = components["schemas"];
type Operations = operations;

export type JournalListItem = Schemas["JournalListItem"];

export type DealLink = Schemas["DealLinkOut"];

export type DealOut = Schemas["DealOut"];

export type JournalDetailResponse = Schemas["JournalDetailResponse"];

export type JournalSearchResponse = Schemas["JournalSearchResponse"];

/** List row plus the covering deals' names and the best green OA route. */
export type JournalBatchItem = Schemas["JournalBatchItem"];

export type JournalBatchResponse = Schemas["JournalBatchResponse"];

/** Three similar-journal cuts: institution-publishing venues, deal-covered venues, and the general list. */
export type SimilarJournalsBundle = Schemas["SimilarJournalsBundle"];

export type OpenalexTopic = Schemas["OpenalexTopicOut"];

export type OpenalexSource = Schemas["OpenalexInfo"];

/** Institution work metrics computed from OpenAlex works. */
export type InstitutionMetrics = Schemas["InstitutionMetrics"];

export type WorksPage = Schemas["WorksPage"];

/** OpenAIRE cross-check facts for one journal. */
export type OpenaireInfo = Schemas["OpenaireInfo"];

export type LimitationOut = Schemas["LimitationOut"];
export type FreshnessResponse = Schemas["FreshnessResponse"];
export type StatsYear = Schemas["StatsYear"];
export type OpenalexOnly = Schemas["OpenalexOnly"];
export type PartsRollup = Schemas["PartsRollup"];
export type CrisGapsResponse = Schemas["CrisGapsResponse"];
export type FunderListItem = Schemas["FunderListItem"];
export type FunderSearchResponse = Schemas["FunderSearchResponse"];
export type FunderDetailResponse = Schemas["FunderDetailResponse"];
export type FunderFitOut = Schemas["FunderFitOut"];
export type Attribution = Schemas["Attribution"];

// --- Collaboration partners (ROR-identified co-author institutions) ---

export type CollaborationPartner = Schemas["CollaborationPartner"];
export type CollaborationSearchResponse = Schemas["CollaborationSearchResponse"];
export type CollaborationFacets = Schemas["CollaborationFacets"];
/** The row the API sends for one partner on the map, in field order. */
type CollaborationMapRow = Schemas["CollaborationMapResponse"]["items"][number];

/**
 * One partner with coordinates. The API sends a row per partner to keep
 * the map payload small; fetchCollaborationMap turns each row into this.
 */
export type CollaborationMapPoint = {
  ror: string;
  name: string;
  country_code: string | null;
  city: string | null;
  org_type: string;
  lat: number;
  lng: number;
  works: number;
  corresponding_works: number;
  home_corresponding_works: number;
  oa_share: number | null;
};

export type CollaborationMapResponse = {
  items: CollaborationMapPoint[];
  unmapped: number;
};
export type CollaborationDetailResponse = Schemas["CollaborationDetailResponse"];
export type CollaborationWork = Schemas["CollaborationWork"];
export type CollaborationWorksResponse = Schemas["CollaborationWorksResponse"];
export type CollaborationTrendYear = Schemas["CollaborationTrendYear"];
export type PartnerSummary = Schemas["PartnerSummary"];

/** Multi-select filters. The API splits each of them on "|". */
export const COLLAB_MULTI_KEYS = [
  "type",
  "country",
  "faculty",
  "oa_status",
  "topic",
  "funder",
  "project",
  "source",
] as const;
export type CollabMultiKey = (typeof COLLAB_MULTI_KEYS)[number];

export type CollaborationSort =
  | "works"
  | "name"
  | "corresponding_works"
  | "home_corresponding_works"
  | "oa_share";
export type CollaborationLevel = "faculty" | "group" | "institute";
export type CollaborationSize = "standard" | "small" | "all";
export type CollaborationLead = "all" | "home" | "partner";

/** Filters shared by the partner list, map, detail and works endpoints. */
export type CollaborationSearchParams = {
  q?: string;
  year_from?: number;
  year_to?: number;
  level?: CollaborationLevel;
  size?: CollaborationSize;
  rollup?: boolean;
  lead?: CollaborationLead;
  min_works?: number;
  shares_deals?: boolean;
  sort?: CollaborationSort;
  dir?: "asc" | "desc";
} & Partial<Record<CollabMultiKey, string[]>>;

export const COLLAB_PAGE_SIZE = 25;

function collabParams(p: CollaborationSearchParams): Record<string, string | undefined> {
  return {
    q: p.q?.trim() || undefined,
    year_from: p.year_from === undefined ? undefined : String(p.year_from),
    year_to: p.year_to === undefined ? undefined : String(p.year_to),
    level: p.level,
    size: p.size && p.size !== "standard" ? p.size : undefined,
    rollup: p.rollup === false ? "false" : undefined,
    lead: p.lead && p.lead !== "all" ? p.lead : undefined,
    min_works: p.min_works && p.min_works > 1 ? String(p.min_works) : undefined,
    shares_deals: p.shares_deals ? "true" : undefined,
    sort: p.sort,
    dir: p.dir,
    type: p.type?.join("|"),
    country: p.country?.join("|"),
    faculty: p.faculty?.join("|"),
    oa_status: p.oa_status?.join("|"),
    topic: p.topic?.join("|"),
    funder: p.funder?.join("|"),
    project: p.project?.join("|"),
    source: p.source?.join("|"),
  };
}

export function collaborationsRequest(
  inst: string,
  p: CollaborationSearchParams,
  offset: number,
): ApiRequest {
  return {
    path: `/${inst}/collaborations`,
    query: { ...collabParams(p), offset, limit: COLLAB_PAGE_SIZE, include_credits: "false" },
  };
}

export function fetchCollaborations(
  inst: string,
  p: CollaborationSearchParams,
  offset: number,
  signal?: AbortSignal,
) {
  return getRequest<CollaborationSearchResponse>(collaborationsRequest(inst, p, offset), signal);
}

function collaborationMapRequest(inst: string, p: CollaborationSearchParams): ApiRequest {
  return { path: `/${inst}/collaborations/map`, query: collabParams(p) };
}

/** The map endpoint sends compact rows; the page reads named points. */
function toCollaborationMap(data: Schemas["CollaborationMapResponse"]) {
  const toPoint = ([
    ror,
    name,
    country_code,
    city,
    org_type,
    lat,
    lng,
    works,
    corresponding_works,
    home_corresponding_works,
    oa_share,
  ]: CollaborationMapRow) => ({
    ror,
    name,
    country_code,
    city,
    org_type,
    lat,
    lng,
    works,
    corresponding_works,
    home_corresponding_works,
    oa_share,
  });
  return { items: data.items.map(toPoint), unmapped: data.unmapped };
}

export function fetchCollaborationMap(
  inst: string,
  p: CollaborationSearchParams,
  signal?: AbortSignal,
) {
  return getRequest<Schemas["CollaborationMapResponse"]>(
    collaborationMapRequest(inst, p),
    signal,
  ).then(toCollaborationMap);
}

export function collaborationRequest(
  inst: string,
  ror: string,
  p: CollaborationSearchParams,
): ApiRequest {
  return {
    path: `/${inst}/collaborations/${encodeURIComponent(ror)}`,
    query: { ...collabParams(p), include_works: "false" },
  };
}

export function fetchCollaboration(
  inst: string,
  ror: string,
  p: CollaborationSearchParams,
  signal?: AbortSignal,
) {
  return getRequest<CollaborationDetailResponse>(collaborationRequest(inst, ror, p), signal);
}

export function collaborationWorksRequest(
  inst: string,
  ror: string,
  p: CollaborationSearchParams,
  offset: number,
  limit: number = COLLAB_PAGE_SIZE,
): ApiRequest {
  return {
    path: `/${inst}/collaborations/${encodeURIComponent(ror)}/works`,
    query: { ...collabParams(p), offset, limit },
  };
}

export function fetchCollaborationWorks(
  inst: string,
  ror: string,
  p: CollaborationSearchParams,
  offset: number,
  limit: number = COLLAB_PAGE_SIZE,
  signal?: AbortSignal,
) {
  return getRequest<CollaborationWorksResponse>(
    collaborationWorksRequest(inst, ror, p, offset, limit),
    signal,
  );
}

function collabCsvHref(inst: string, p: CollaborationSearchParams, tail: string): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(collabParams(p))) {
    if (value) qs.set(key, value);
  }
  const query = qs.toString();
  return `/api/v1/${inst}/collaborations${tail}${query ? `?${query}` : ""}`;
}

/** CSV export of the filtered partner list, or of one partner's works with
 * `ror`. The anchor goes through the same /api proxy as apiGet. */
export function collaborationCsvHref(
  inst: string,
  p: CollaborationSearchParams,
  ror?: string,
): string {
  return collabCsvHref(inst, p, ror ? `/${encodeURIComponent(ror)}/works.csv` : "/partners.csv");
}

/** CSV export of the per-year trend: collaborative works by partner
 * organisation type, location and open access status. */
export function collaborationTrendCsvHref(inst: string, p: CollaborationSearchParams): string {
  return collabCsvHref(inst, p, "/trend.csv");
}

export type BudgetMode = NonNullable<Schemas["RecommendRequest"]["budget_mode"]>;
export type RecommendRequest = Schemas["RecommendRequest"];
export type RecommendResponse = Schemas["RecommendResponse"];
export type RecommendedJournal = Schemas["RecommendedJournal"];
export type RecommendReason = Schemas["RecommendReason"];
export type RecommendDealSummary = Schemas["RecommendDealSummary"];
export type RecommendApcDisplay = Schemas["RecommendApcDisplay"];

// --- Author profiles (Pure-based, per institution) ---

export type AuthorSearchItem = Schemas["AuthorItem"];

export type AuthorFacetBucket = Schemas["AuthorFacet"];

/** Author search ordering; the backend default is works_desc. Derived from
 * the generated enum in search_authors (GET /{inst}/authors). */
type AuthorsSearchQuery = NonNullable<
  Operations["search_authors_api_v1__institution_code__authors_get"]["parameters"]["query"]
>;
export type AuthorSearchSort = NonNullable<AuthorsSearchQuery["sort"]>;

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

/** Compact parent-work reference of an OpenAlex-side row ({id, name, rel}). */
export type WorkParent = Schemas["WorkParent"];

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

/** Journals search scope. The backend validates this as a regex pattern, so
 * the generated types carry it as `string`; the union mirrors
 * `^(all|title|publisher|topic)$` in openapi.json. Named JournalsSearchIn to
 * avoid the generated usage-event schema SearchIn. */
export type JournalsSearchIn = "all" | "title" | "publisher" | "topic";

/** Publication-year range params accepted by the works/profile/detail/CSV
 * endpoints; the global year lens feeds these. */
export type YearParams = { year_from?: number; year_to?: number };

export type JournalSearchParams = {
  q?: string;
  search_in?: JournalsSearchIn;
  deal?: "any" | "covered" | "not_covered";
  deal_id?: number;
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
  /** Only journals with works in the current or previous year; on by default. */
  active?: boolean;
  /** Only journals on a curated list (Scimago, DOAJ, deal, national lists); on by default. */
  vouched?: boolean;
  sort?: SortKey;
  /** Sort direction; omitted = each key's natural direction. */
  dir?: "asc" | "desc";
  cursor?: string;
  limit?: number;
  include_facets?: boolean;
};

/** Error with an HTTP status; message stays technical (console only). */
export class ApiError extends Error {
  status: number;
  constructor(status: number, path: string) {
    super(`API ${status} on ${path}`);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * Human copy for fetch failures; the raw error is already in the console
 * (apiGet logs it). Maps the statuses the UI can actually hit. Sentences
 * live under common.errors.
 */
export function errorMessage(t: LabelT, err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 400 || err.status === 422) return t("errors.badRequest");
    if (err.status === 404) return t("errors.notFound");
    if (err.status >= 500) return t("errors.server");
  }
  return t("errors.unknown");
}

function combinedSignal(
  signal?: AbortSignal,
  timeoutMs: number = 30_000,
): { signal: AbortSignal; cleanup: () => void } {
  const timeout = AbortSignal.timeout(timeoutMs);
  if (!signal) return { signal: timeout, cleanup: () => {} };
  if (typeof AbortSignal.any === "function") {
    return { signal: AbortSignal.any([signal, timeout]), cleanup: () => {} };
  }
  const controller = new AbortController();
  const abort = () => controller.abort(signal.reason);
  if (signal.aborted) {
    controller.abort(signal.reason);
    return { signal: controller.signal, cleanup: () => {} };
  }
  signal.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(
    () => controller.abort(new DOMException("TimeoutError", "TimeoutError")),
    timeoutMs,
  );
  return {
    signal: controller.signal,
    cleanup: () => {
      signal.removeEventListener("abort", abort);
      clearTimeout(timer);
    },
  };
}

/** GET helper against the same-origin /api proxy (next.config.mjs rewrites). */
export async function apiGet<T>(
  path: string,
  params?: Record<string, string | number | boolean | undefined | null>,
  signal?: AbortSignal,
): Promise<T> {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const qs = search.toString();
  const reqSignal = combinedSignal(signal);
  try {
    const res = await fetch(`/api/v1${path}${qs ? `?${qs}` : ""}`, {
      cache: "no-store",
      // A hung backend must surface as an error, not endless skeletons.
      signal: reqSignal.signal,
    });
    if (!res.ok) {
      console.error(`API ${res.status} on ${path}`);
      trackApiError("GET", path, res.status);
      throw new ApiError(res.status, path);
    }
    return (await res.json()) as T;
  } catch (err) {
    if (!(err instanceof ApiError) && !signal?.aborted) {
      console.error(`Fetch failed on ${path}`, err);
    }
    throw err;
  } finally {
    reqSignal.cleanup();
  }
}

/** Query-string values of a backend GET; null, undefined and "" are dropped. */
export type ApiQuery = Record<string, string | number | boolean | null | undefined>;

/**
 * One backend GET as plain data: the path after /api/v1 and its query. The
 * browser hooks send it with getRequest; a server render sends the same
 * request with fetchForRender (lib/server-fetch) and seeds the cache under the
 * hook's key, so the server-rendered and browser-fetched documents match.
 */
export type ApiRequest = { path: string; query?: ApiQuery };

/** apiGet for a request built by one of the *Request builders below. */
export function getRequest<T>(request: ApiRequest, signal?: AbortSignal): Promise<T> {
  return apiGet<T>(request.path, request.query, signal);
}

/** Journal search: full-text and filtered, or "journals like this text". */
export function journalsRequest(
  inst: string,
  params: JournalSearchParams,
  semantic: boolean,
): ApiRequest {
  if (!semantic) return { path: `/${inst}/journals`, query: { ...params } };
  // Free-text "journals like this description": embeddings, not FTS.
  // Filter/sort params do not apply to the vector ranking, but the cursor
  // does: the endpoint pages by offset into its ranking. The eligibility
  // toggles apply too; both are server-side defaults, so they travel only
  // when switched off.
  return {
    path: `/${inst}/journals/semantic-search`,
    query: {
      q: params.q ?? "",
      limit: params.limit ?? 40,
      cursor: params.cursor,
      active: params.active,
      vouched: params.vouched,
    },
  };
}

/** The filter part of a journal search: facets ignore paging, sort, and the
 * free text, so a zero-hit query still shows which values exist. */
export function facetFilters(params: JournalSearchParams): JournalSearchParams {
  const { cursor: _c, sort: _s, limit: _l, q: _q, search_in: _si, ...filters } = params;
  return filters;
}

export function facetsRequest(inst: string, filters: JournalSearchParams): ApiRequest {
  return { path: `/${inst}/journals`, query: { ...filters, include_facets: true, limit: 1 } };
}

export function journalWorksRequest(
  inst: string,
  issnL: string,
  page: number,
  years?: YearParams,
): ApiRequest {
  return {
    path: `/${inst}/journals/${encodeURIComponent(issnL)}/works`,
    query: { page, page_size: 10, year_from: years?.year_from, year_to: years?.year_to },
  };
}

export function similarRequest(inst: string, issnL: string): ApiRequest {
  return { path: `/${inst}/journals/${encodeURIComponent(issnL)}/similar` };
}

export function dealsRequest(inst: string, status: "current" | "archive" | "all"): ApiRequest {
  return { path: `/${inst}/deals`, query: { status } };
}

export function limitationsRequest(inst: string): ApiRequest {
  return { path: `/${inst}/meta/limitations` };
}

export function freshnessRequest(inst: string): ApiRequest {
  return { path: `/${inst}/meta/freshness` };
}

export function institutionsRequest(): ApiRequest {
  return { path: "/institutions" };
}

export function funderDirectoryRequest(inst: string, params: FunderSearchParams): ApiRequest {
  return {
    path: `/${inst}/funders`,
    query: {
      q: params.q || undefined,
      country: params.country?.join("|"),
      policy_structured:
        params.policy_structured === undefined ? undefined : String(params.policy_structured),
      has_works: params.has_works === undefined ? undefined : String(params.has_works),
      oa_publishing: params.oa_publishing?.join("|"),
      green_archiving: params.green_archiving?.join("|"),
      data_policy: params.data_policy?.join("|"),
      sort: params.sort,
      dir: params.dir,
      offset: params.offset ?? 0,
      limit: params.limit ?? 50,
      year_from: params.year_from,
      year_to: params.year_to,
    },
  };
}

/** POST helper against the same-origin /api proxy. Never logs request bodies. */
export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  try {
    const res = await fetch(`/api/v1${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
      signal: AbortSignal.timeout(30_000),
    });
    if (!res.ok) {
      console.error(`API ${res.status} on ${path}`);
      trackApiError("POST", path, res.status);
      throw new ApiError(res.status, path);
    }
    return (await res.json()) as T;
  } catch (err) {
    if (!(err instanceof ApiError)) console.error(`Fetch failed on ${path}`, err);
    throw err;
  }
}

/** Guided Journal Finder recommendation endpoint; manuscript text stays private. */
export async function recommendJournals(
  inst: string,
  req: RecommendRequest,
): Promise<RecommendResponse> {
  return apiPost<RecommendResponse>(`/${inst}/journals/recommend`, req);
}

export function authorsRequest(
  inst: string,
  q?: string,
  filters: AuthorSearchFilters = {},
  opts: AuthorFetchOptions = {},
): ApiRequest {
  return {
    path: `/${inst}/authors`,
    query: {
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
    },
  };
}

export async function fetchAuthor(
  inst: string,
  pureUuid: string,
  years?: YearParams,
  signal?: AbortSignal,
): Promise<AuthorProfile> {
  return apiGet<AuthorProfile>(
    `/${inst}/authors/${encodeURIComponent(pureUuid)}`,
    {
      year_from: years?.year_from,
      year_to: years?.year_to,
    },
    signal,
  );
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

/** Part-kind filter on the publisher detail and gap-CSV endpoints; matches
 * the backend ?parts= values. */
export type PublisherPartsFilter = "chapter" | "part" | "standalone";

/** List params for the publisher surface; arrays are pipe-joined in the query. */
export type FunderSearchSort = "works" | "name";

export type FunderSearchParams = {
  q?: string;
  country?: string[];
  policy_structured?: boolean;
  has_works?: boolean;
  oa_publishing?: string[];
  green_archiving?: string[];
  data_policy?: string[];
  sort?: FunderSearchSort;
  dir?: "asc" | "desc";
  offset?: number;
  limit?: number;
  year_from?: number;
  year_to?: number;
};

export type PublisherSearchParams = {
  q?: string;
  oa_type?: string[];
  /** Canonical backend value; legacy "none" URLs are normalized client-side. */
  deal?: "covered" | "not_covered";
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
  year_from?: number;
  year_to?: number;
};

/** Org-unit hierarchy level; institutes (MESA+, TechMed, DSI) are their
 * own level, separate from faculties and research groups. */
export type OrgUnitLevel = "faculty" | "group" | "institute";

export type OrgUnitItem = Schemas["OrgUnitItem"];

export type OrgUnitSearchResponse = Schemas["OrgUnitSearchResponse"];

export type OrgUnitDetailResponse = Schemas["OrgUnitDetailResponse"];

export type OrgUnitSearchSort = "relevance" | "name" | "authors" | "works" | "deal_works";

/** Top-authors card ordering on org-unit detail pages. */
export type OrgUnitAuthorSort = "share" | "works";

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
  year_from?: number;
  year_to?: number;
};

/** Unit names contain spaces, commas, "&" and "/": encode each segment,
 * keep "/" so the backend {name:path} route still resolves. */
export function encodeNamePath(name: string): string {
  return name.split("/").map(encodeURIComponent).join("/");
}

/** Usage filter dump for directory fetchers: paging keys stripped. */
export function usageDirectoryFilters(params: object): Record<string, unknown> | undefined {
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

export function publishersRequest(inst: string, params: PublisherSearchParams = {}): ApiRequest {
  return {
    path: `/${inst}/publishers`,
    query: {
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
      year_from: params.year_from,
      year_to: params.year_to,
    },
  };
}

export async function fetchPublisher(
  inst: string,
  name: string,
  years?: YearParams,
  parts?: PublisherPartsFilter,
  includeGaps: boolean = false,
  signal?: AbortSignal,
): Promise<PublisherDetailResponse> {
  return apiGet<PublisherDetailResponse>(
    `/${inst}/publishers/${encodeNamePath(name)}`,
    {
      year_from: years?.year_from,
      year_to: years?.year_to,
      parts,
      include_gaps: includeGaps ? undefined : "false",
    },
    signal,
  );
}

export async function fetchPublisherCrisGaps(
  inst: string,
  name: string,
  years?: YearParams,
  parts?: PublisherPartsFilter,
  signal?: AbortSignal,
): Promise<CrisGapsResponse> {
  return apiGet<CrisGapsResponse>(
    `/${inst}/publishers/${encodeNamePath(name)}/cris-gaps`,
    {
      year_from: years?.year_from,
      year_to: years?.year_to,
      parts,
    },
    signal,
  );
}

export function orgUnitsRequest(inst: string, params: OrgUnitSearchParams = {}): ApiRequest {
  return {
    path: `/${inst}/orgunits`,
    query: {
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
      year_from: params.year_from,
      year_to: params.year_to,
    },
  };
}

export async function fetchOrgUnit(
  inst: string,
  level: OrgUnitLevel,
  name: string,
  years?: YearParams,
  sort?: OrgUnitAuthorSort,
  includeGaps: boolean = false,
  signal?: AbortSignal,
): Promise<OrgUnitDetailResponse> {
  return apiGet<OrgUnitDetailResponse>(
    `/${inst}/orgunits/${level}/${encodeNamePath(name)}`,
    {
      year_from: years?.year_from,
      year_to: years?.year_to,
      sort,
      include_gaps: includeGaps ? undefined : "false",
    },
    signal,
  );
}

export async function fetchOrgUnitCrisGaps(
  inst: string,
  level: OrgUnitLevel,
  name: string,
  years?: YearParams,
  parts?: PublisherPartsFilter,
  signal?: AbortSignal,
): Promise<CrisGapsResponse> {
  return apiGet<CrisGapsResponse>(
    `/${inst}/orgunits/${level}/${encodeNamePath(name)}/cris-gaps`,
    {
      year_from: years?.year_from,
      year_to: years?.year_to,
      parts,
    },
    signal,
  );
}

export async function fetchJournalCrisGaps(
  inst: string,
  issnL: string,
  years?: YearParams,
  parts?: PublisherPartsFilter,
  signal?: AbortSignal,
): Promise<CrisGapsResponse> {
  return apiGet<CrisGapsResponse>(
    `/${inst}/journals/${encodeURIComponent(issnL)}/cris-gaps`,
    {
      year_from: years?.year_from,
      year_to: years?.year_to,
      parts,
    },
    signal,
  );
}

/** ISSN-Ls per batch request: the endpoint's cap. */
export const JOURNAL_BATCH_SIZE = 100;

/** Saved-journal lookup (shortlist). A longer list goes out in slices of
 * JOURNAL_BATCH_SIZE; the merged answer keeps the request order, and
 * `missing` names the ISSN-Ls outside the institution's browsable corpus. */
export async function fetchJournalBatch(
  inst: string,
  issnLs: string[],
  years?: YearParams,
  signal?: AbortSignal,
): Promise<JournalBatchResponse> {
  const slices: string[][] = [];
  for (let i = 0; i < issnLs.length; i += JOURNAL_BATCH_SIZE) {
    slices.push(issnLs.slice(i, i + JOURNAL_BATCH_SIZE));
  }
  const parts = await Promise.all(
    slices.map((slice) =>
      apiGet<JournalBatchResponse>(
        `/${inst}/journals/batch`,
        {
          issn_l: slice.join(","),
          year_from: years?.year_from,
          year_to: years?.year_to,
        },
        signal,
      ),
    ),
  );
  return {
    items: parts.flatMap((part) => part.items),
    missing: parts.flatMap((part) => part.missing),
  };
}
