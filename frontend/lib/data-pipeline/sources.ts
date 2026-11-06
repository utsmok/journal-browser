export type SourceRow = {
  name: string;
  provides: string;
  transport: string;
  usedBy: string;
};

export const SOURCES: SourceRow[] = [
  {
    name: "OpenAlex",
    provides: "journal universe, works, author profiles, publishers, funders, OA color samples",
    transport:
      "REST with cursor pagination; per-DOI single GETs are preferred over filter queries; honors OPENALEX_API_KEY",
    usedBy:
      "journals, publishers, oa-colors, stats, enrich, author-ids; manual: funder sweeps, work funders, Emerald contract",
  },
  {
    name: "Crossref",
    provides: "DOI metadata for journal resolution",
    transport: "REST, 50 DOIs per request, polite pool with mailto contact",
    usedBy: "enrich (second rung)",
  },
  {
    name: "OpenAIRE Graph API",
    provides: "institution research products; curated funder canon",
    transport:
      "REST via aireloom, 100 per page; skips the institution when no org id is configured",
    usedBy: "openaire; manual: funder canon",
  },
  {
    name: "Pure OAI-PMH (ris.utwente.nl)",
    provides: "institution publications, CERIF author lists, org units, persons",
    transport:
      "OAI-PMH ListRecords with resumption tokens, at least 1 s between requests, anonymous",
    usedBy: "pure, pure-cerif, pure-entities",
  },
  {
    name: "openaccess.nl",
    provides: "Dutch publisher OA deal register",
    transport: "HTML pages scraped strictly sequentially",
    usedBy: "deals-openaccess-nl",
  },
  {
    name: "JCT (cOAlition S)",
    provides: "deal ESAC ids and journal lists",
    transport: "published Google Sheets CSVs, 0.5 to 1.5 s jitter between agreements",
    usedBy: "deals-jct",
  },
  {
    name: "OpenAPC",
    provides: "per-article APC and transformative agreement costs",
    transport: "five raw CSV files from GitHub",
    usedBy: "openapc",
  },
  {
    name: "DOAJ",
    provides: "journal OA canon with APC flags",
    transport: "one full CSV download from doaj.org/csv",
    usedBy: "doaj",
  },
  {
    name: "Scimago Journal Rank",
    provides: "SJR indicator and quartile per year",
    transport: "tracked seed CSVs in backend/data/scimagojr (the site blocks scripted clients)",
    usedBy: "scimagojr",
  },
  {
    name: "Jisc Open Policy Finder",
    provides: "publisher OA policies, funder canon, repository list",
    transport: "REST with x-api-key header, search_after paging, 0.15 s default sleep",
    usedBy: "manual: harvest_jisc + normalize_jisc",
  },
  {
    name: "ip-api.com",
    provides: "country codes for usage events",
    transport: "batch POST of up to 100 IPs, 4.5 s spacing on the free tier",
    usedBy: "manual: enrich_usage_geo",
  },
  {
    name: "Pure portal (research.utwente.nl)",
    provides: "organisation parents and person-org links the OAI feed lacks",
    transport: "RSS pages with a browser user agent, 2 s delay",
    usedBy: "manual: harvest_pure_portal, harvest_portal_persons",
  },
  {
    name: "ut-metadata platform",
    provides: "canonical works of the previous platform",
    transport: "read-only Postgres DSN (JB_UT_METADATA_DSN); no HTTP",
    usedBy: "authors (--source utmd), one-shot importers, dev checks",
  },
  {
    name: "BAAI/bge-small-en-v1.5",
    provides: "384-dim journal embeddings",
    transport: "local ONNX via fastembed, no network",
    usedBy: "embeddings",
  },
];
