import type { components } from "./api-types";

export type Schemas = components["schemas"];

/**
 * The generated types trail the backend contract (api-types.ts is
 * auto-generated). Fields the updated backend adds are declared here so the
 * frontend can code against them while the old backend simply omits them.
 */
export type JournalListItem = Schemas["JournalListItem"] & {
  apc_euro_mean?: number | null;
  apc_period?: number | null;
  oa_type?: ("gold" | "diamond" | "hybrid" | "subscription") | null;
};

export type DealLink = {
  url: string;
  text: string;
  category:
    | "workflow"
    | "contract"
    | "contact"
    | "publisher_page"
    | "publisher_site"
    | "journal_browser"
    | "openaccessnl_doc"
    | "flyer"
    | "other";
};

export type DealOut = Schemas["DealOut"] & { links?: DealLink[] };

export type JournalDetailResponse = Schemas["JournalDetailResponse"] & {
  journal: JournalListItem;
  openalex?: OpenalexSource | null;
  openaire?: { matched_works: number } | null;
  twente_metrics?: TwenteMetrics | null;
};

export type JournalSearchResponse = Schemas["JournalSearchResponse"];

export type SimilarJournal = {
  issn_l: string;
  title: string | null;
  publisher_name: string | null;
  quartile?: string | null;
  is_oa?: boolean | null;
  deal_covered?: boolean;
  twente_works?: number;
  shared_topics: number;
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

/** Twente-affiliated work metrics computed from OpenAlex works. */
export type TwenteMetrics = {
  openalex_matched: number;
  fwci_avg: number | null;
  fwci_n: number;
  retracted: number;
  cited_total: number;
  // ut-metadata-grounded totals; null when the canonical store is unreachable.
  ut_total?: number | null;
  ut_retracted?: number | null;
  ut_oa?: {
    gold?: number;
    hybrid?: number;
    green?: number;
    bronze?: number;
    diamond?: number;
    closed?: number;
    unknown?: number;
  } | null;
};

export type JournalWork = {
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
  topic?: string;
  sort?: SortKey;
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
