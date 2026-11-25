import type {
  CollaborationSearchParams,
  JournalSearchParams,
  OrgUnitAuthorSort,
  OrgUnitLevel,
  OrgUnitSearchParams,
  PublisherSearchParams,
} from "@/lib/api";

/**
 * TanStack Query key factory: one place owns every cache key shape.
 * Every key leads with the institution code — two hosted universities
 * must never share cache entries.
 *
 * Detail keys end with the scope a visitor can change in the browser
 * (funder, year range, author sort). Those parts default to null, which is
 * the unscoped document: the server fetches it and seeds the cache under the
 * same key (see SeededQuery), so the page renders on the server and the
 * browser does not fetch it again.
 */
export const qk = {
  journals: (i: string, params: JournalSearchParams) => ["journals", i, params] as const,
  facets: (i: string, filters: JournalSearchParams) => ["facets", i, filters] as const,
  journal: (
    i: string,
    issnL: string,
    funderId: number | null = null,
    yearFrom: number | null = null,
    yearTo: number | null = null,
  ) => ["journal", i, issnL, funderId, yearFrom, yearTo] as const,
  journalGaps: (i: string, issnL: string) => ["journal-gaps", i, issnL] as const,
  similar: (i: string, issnL: string) => ["similar", i, issnL] as const,
  works: (i: string, issnL: string, page: number) => ["works", i, issnL, page] as const,
  deals: (i: string, status: "current" | "archive" | "all") => ["deals", i, status] as const,
  limitations: (i: string) => ["limitations", i] as const,
  freshness: (i: string) => ["freshness", i] as const,
  institutions: () => ["institutions"] as const,
  publishers: (i: string, params: PublisherSearchParams) => ["publishers", i, params] as const,
  publisher: (
    i: string,
    name: string,
    yearFrom: number | null = null,
    yearTo: number | null = null,
  ) => ["publisher", i, name, yearFrom, yearTo] as const,
  publisherGaps: (i: string, name: string) => ["publisher-gaps", i, name] as const,
  orgunits: (i: string, params: OrgUnitSearchParams) => ["orgunits", i, params] as const,
  orgunit: (
    i: string,
    level: OrgUnitLevel,
    name: string,
    yearFrom: number | null = null,
    yearTo: number | null = null,
    sort: OrgUnitAuthorSort = "share",
  ) => ["orgunit", i, level, name, yearFrom, yearTo, sort] as const,
  orgunitGaps: (i: string, level: OrgUnitLevel, name: string) =>
    ["orgunit-gaps", i, level, name] as const,
  funders: (i: string, q: string) => ["funders", i, q] as const,
  funder: (i: string, id: number, yearFrom: number | null = null, yearTo: number | null = null) =>
    ["funder", i, id, yearFrom, yearTo] as const,
  author: (
    i: string,
    authorId: string,
    yearFrom: number | null = null,
    yearTo: number | null = null,
  ) => ["author", i, authorId, yearFrom, yearTo] as const,
  collaborations: (i: string, p: CollaborationSearchParams, offset: number) =>
    ["collaborations", i, p, offset] as const,
  collaborationMap: (i: string, p: CollaborationSearchParams) =>
    ["collaboration-map", i, p] as const,
  collaboration: (i: string, ror: string, p: CollaborationSearchParams) =>
    ["collaboration", i, ror, p] as const,
  collaborationWorks: (i: string, ror: string, p: CollaborationSearchParams, offset: number) =>
    ["collaboration-works", i, ror, p, offset] as const,
};
