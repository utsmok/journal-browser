import type { JournalSearchParams, JournalsSearchIn, SortKey } from "@/lib/api";

/**
 * Pure URL-to-params mapping for the journal search landing. The client
 * component feeds it `useSearchParams()`, the server page feeds it Next's
 * `searchParams` (as a URLSearchParams), so both sides compute identical
 * query keys and the seeded documents match what the browser would fetch.
 */

export type JournalsLandingView = "browse" | "guide";

/** localStorage lens around the URL params: the selected funder and the
 * publication-year range. Both hydrate after mount, so the server and the
 * first client render pass nothing here and compute the unscoped query. */
export type JournalsLandingLens = {
  /** Selected funder pref, as useFunderPrefs returns it. */
  funder?: { id: number } | null;
  yearFrom?: number | null;
  yearTo?: number | null;
};

/** Everything journals-landing derives from the URL, plus the
 * JournalSearchParams its useJournals and useFacets hooks receive. */
export type JournalsLandingParams = {
  view: JournalsLandingView;
  q: string;
  sort: SortKey;
  dir: "asc" | "desc" | null;
  deal: string;
  dealId: number | undefined;
  oa: string | null;
  doaj: string | null;
  quartiles: string[];
  topics: string[];
  publishers: string[];
  hasApc: string | null;
  hasWorks: string | null;
  greenOas: string[];
  active: boolean;
  vouched: boolean;
  searchIn: JournalsSearchIn;
  oaTypes: string[];
  pubTypes: string[];
  languages: string[];
  semanticMode: boolean;
  /** The semantic request runs only in browse view with a query of 2+ chars. */
  semantic: boolean;
  funderFits: string[];
  cursor: string | undefined;
  /** Params object the hooks receive, with the funder and year lens applied. */
  query: JournalSearchParams;
};

const splitPipe = (raw: string | null): string[] => (raw ?? "").split("|").filter(Boolean);
const splitEnum = (raw: string | null): string[] => (raw ?? "").split(/[|,]/).filter(Boolean);

export function journalsLandingParams(
  sp: URLSearchParams,
  initialView: JournalsLandingView = "browse",
  lens: JournalsLandingLens = {},
): JournalsLandingParams {
  const spView = sp.get("view");
  const view: JournalsLandingView =
    spView === "guide" || (initialView === "guide" && spView !== "browse") ? "guide" : "browse";

  const q = sp.get("q") ?? "";
  const sort = (sp.get("sort") ?? (q ? "relevance" : "institution_works")) as SortKey;
  const dirParam = sp.get("dir");
  const dir: "asc" | "desc" | null = dirParam === "asc" || dirParam === "desc" ? dirParam : null;
  const deal = sp.get("deal") ?? "";
  const dealIdRaw = sp.get("deal_id");
  const dealId = dealIdRaw && /^\d+$/.test(dealIdRaw) ? Number(dealIdRaw) : undefined;
  const oa = sp.get("oa");
  const doaj = sp.get("doaj");
  const quartiles = splitEnum(sp.get("quartile"));
  const topics = splitPipe(sp.get("topic"));
  const publishers = splitPipe(sp.get("publisher"));
  const hasApc = sp.get("has_apc");
  const hasWorks = sp.get("has_works");
  const greenOas = splitEnum(sp.get("green_oa"));
  // Eligibility toggles: both on by default, URL param only when off so
  // default URLs stay clean.
  const active = sp.get("active") !== "false";
  const vouched = sp.get("vouched") !== "false";
  const searchIn = (sp.get("search_in") ?? "all") as JournalsSearchIn;
  const oaTypes = splitEnum(sp.get("oa_type"));
  const pubTypes = splitPipe(sp.get("pub_type"));
  const languages = splitEnum(sp.get("language"));
  const semanticMode = sp.get("mode") === "semantic";
  const semantic = view === "browse" && semanticMode && q.trim().length >= 2;
  const funderFits = splitEnum(sp.get("funder_fit"));
  const cursor = sp.get("cursor") ?? undefined;

  const query: JournalSearchParams = {
    q: q || undefined,
    search_in: searchIn === "all" ? undefined : searchIn,
    deal: (deal || undefined) as "covered" | "not_covered" | undefined,
    deal_id: dealId,
    oa: oa === null ? undefined : oa === "true",
    doaj: doaj === null ? undefined : doaj === "true",
    quartile: quartiles.join("|") || undefined,
    publisher: publishers.join("|") || undefined,
    has_apc: hasApc === null ? undefined : hasApc === "true",
    has_works: hasWorks === null ? undefined : hasWorks === "true",
    green_oa: greenOas.join("|") || undefined,
    funder: lens.funder && !semanticMode ? lens.funder.id : undefined,
    funder_fit: funderFits.join("|") || undefined,
    topic: topics.join("|") || undefined,
    oa_type: oaTypes.join(",") || undefined,
    pub_type: pubTypes.join("|") || undefined,
    language: languages.join(",") || undefined,
    year_from: lens.yearFrom ?? undefined,
    year_to: lens.yearTo ?? undefined,
    // Off travels to the API; on stays out (server defaults to on).
    active: active ? undefined : false,
    vouched: vouched ? undefined : false,
    sort,
    dir: dir ?? undefined,
    cursor,
    limit: 40,
    include_facets: false,
  };

  return {
    view,
    q,
    sort,
    dir,
    deal,
    dealId,
    oa,
    doaj,
    quartiles,
    topics,
    publishers,
    hasApc,
    hasWorks,
    greenOas,
    active,
    vouched,
    searchIn,
    oaTypes,
    pubTypes,
    languages,
    semanticMode,
    semantic,
    funderFits,
    cursor,
    query,
  };
}
