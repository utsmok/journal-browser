import type { components } from "@/lib/api-types";

export type SourceFreshness = components["schemas"]["SourceFreshness"];
export type FreshnessSchedule = components["schemas"]["FreshnessSchedule"];
export type FreshnessStatus = components["schemas"]["FreshnessStatus"];

type SourceInfo = { name: string; harvest: string | null; url: string };

/** What each `source` of /meta/freshness stands for: the name shown in the
 * tables, the `harvest_runs.source` that carries it, and the site where that
 * harvest reads. Mirrors SOURCES in
 * backend/src/journal_browser/services/freshness.py; add a row here when a
 * source is added there. An empty url means the source has no public site
 * (the Pure link is the institution's own portal, the author records are
 * built on this server). */
export const SOURCE_INFO: Record<string, SourceInfo> = {
  pure: { name: "Pure", harvest: "pure", url: "" },
  "openalex-stats": {
    name: "OpenAlex publication counts",
    harvest: "openalex",
    url: "https://openalex.org",
  },
  "openalex-works": {
    name: "OpenAlex publications",
    harvest: "openalex",
    url: "https://openalex.org",
  },
  crossref: { name: "Crossref", harvest: "crossref", url: "https://www.crossref.org" },
  openaire: { name: "OpenAIRE", harvest: "openaire", url: "https://openaire.eu" },
  "openalex-authors": {
    name: "OpenAlex authors",
    harvest: "openalex",
    url: "https://openalex.org",
  },
  authors: { name: "Author records", harvest: "local", url: "" },
  "openalex-journals": {
    name: "OpenAlex journals",
    harvest: "openalex",
    url: "https://openalex.org",
  },
  "openalex-oa": {
    name: "OpenAlex open access status",
    harvest: "openalex",
    url: "https://openalex.org",
  },
  "openalex-funders": {
    name: "OpenAlex funders",
    harvest: "openalex",
    url: "https://openalex.org",
  },
  "openaccess-nl": {
    name: "openaccess.nl",
    harvest: "openaccess.nl",
    url: "https://www.openaccess.nl/en/publishing/publisher-deals",
  },
  jct: {
    name: "Journal Checker Tool (JCT)",
    harvest: "jct",
    url: "https://journalcheckertool.org/transformative-agreements/",
  },
  oaforward: {
    name: "OA Forward agreement registry",
    harvest: "oaforward",
    url: "https://oaforward.org/portfolio/registry-of-open-publishing-agreements/",
  },
  openapc: { name: "OpenAPC", harvest: "openapc", url: "https://github.com/OpenAPC/openapc-de" },
  doaj: { name: "DOAJ", harvest: "doaj", url: "https://doaj.org" },
  // The weekly landing of raw records; only the admin card lists it.
  "jisc-opf": {
    name: "Jisc Open Policy Finder records",
    harvest: "jisc_opf",
    url: "https://openpolicyfinder.jisc.ac.uk",
  },
  "jisc-policies": {
    name: "Jisc Open Policy Finder",
    harvest: "jisc_opf",
    url: "https://openpolicyfinder.jisc.ac.uk",
  },
  scimago: { name: "Scimago", harvest: "scimagojr", url: "https://www.scimagojr.com" },
  ror: { name: "ROR", harvest: null, url: "https://ror.org" },
};

/** Name and link for a freshness row. A source this frontend does not know
 * (the backend added one) is shown under its key. */
export function sourceInfo(source: string): SourceInfo {
  return SOURCE_INFO[source] ?? { name: source, harvest: null, url: "" };
}

/** The site a harvest run of one `harvest_runs.source` reads; "" when there
 * is no site to link to. */
export function harvestUrl(source: string): string {
  return Object.values(SOURCE_INFO).find((info) => info.harvest === source)?.url ?? "";
}

const DAY_MS = 86_400_000;

/** Calendar days between a date and `now`: 0 for today, 1 for yesterday. The
 * time of day is ignored, so 23 hours ago can be a day. */
export function daysAgo(iso: string, now: Date): number {
  const then = new Date(iso);
  then.setHours(0, 0, 0, 0);
  const today = new Date(now);
  today.setHours(0, 0, 0, 0);
  return Math.max(0, Math.round((today.getTime() - then.getTime()) / DAY_MS));
}

const STATUS_RANK: Record<FreshnessStatus, number> = { failed: 0, overdue: 1, ok: 2 };

/** The rows that need attention: the sources whose last refresh failed or
 * that are overdue, the failed ones first. */
export function staleSources(rows: SourceFreshness[]): SourceFreshness[] {
  return rows
    .filter((row) => row.status !== "ok")
    .sort((a, b) => STATUS_RANK[a.status] - STATUS_RANK[b.status]);
}
