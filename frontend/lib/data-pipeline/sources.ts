export type SourceRow = {
  name: string;
  provides: string;
  transport: string;
  usedBy: string;
};

export const SOURCES: SourceRow[] = [
  {
    name: "OpenAlex",
    provides:
      "The journal universe, works, author profiles, publishers, funders, and open-access color samples.",
    transport:
      "REST API with cursor pagination. Single-work requests are preferred over batch filters. Uses OPENALEX_API_KEY when set.",
    usedBy:
      "Bootstrap steps journals, publishers, oa-colors, stats, enrich, and author-ids. Manual steps funder sweeps, work funders, and the Emerald contract import.",
  },
  {
    name: "Crossref",
    provides: "DOI metadata used to resolve journals.",
    transport:
      "REST API through the stavrophora client, 50 DOIs per request, capped at 3 requests per second, in the polite pool. A malformed DOI that fails the batch is isolated by splitting the batch until the bad DOI stands alone.",
    usedBy: "Bootstrap step enrich, second rung.",
  },
  {
    name: "OpenAIRE Graph API",
    provides: "The institution's research products and a curated funder canon.",
    transport:
      "REST API through the aireloom client, 100 per page. Skips the institution when no org id is configured.",
    usedBy: "Bootstrap step openaire. Manual step funder canon.",
  },
  {
    name: "Pure OAI-PMH (ris.utwente.nl)",
    provides: "The institution's publications, CERIF author lists, org units, and persons.",
    transport:
      "OAI-PMH ListRecords with resumption tokens. At least 1 second between requests. Anonymous access.",
    usedBy: "Bootstrap steps pure, pure-cerif, and pure-entities.",
  },
  {
    name: "openaccess.nl",
    provides: "The Dutch open-access deal register.",
    transport: "HTML pages scraped strictly one at a time.",
    usedBy: "Bootstrap step deals-openaccess-nl.",
  },
  {
    name: "JCT (cOAlition S)",
    provides: "Deal ESAC ids and journal lists.",
    transport: "Published Google Sheets as CSV, with a 0.5 to 1.5 second pause between agreements.",
    usedBy: "Bootstrap step deals-jct.",
  },
  {
    name: "OpenAPC",
    provides: "Per-article APC and transformative agreement costs.",
    transport: "Five CSV files from the project's GitHub raw storage.",
    usedBy: "Bootstrap step openapc.",
  },
  {
    name: "DOAJ",
    provides: "The open-access journal canon with APC flags.",
    transport: "One full CSV download from doaj.org/csv.",
    usedBy: "Bootstrap step doaj.",
  },
  {
    name: "Scimago Journal Rank",
    provides: "SJR indicator and quartile per year.",
    transport:
      "Seed CSVs tracked in the repository at backend/data/scimagojr. The Scimago site blocks scripted downloads.",
    usedBy: "Bootstrap step scimagojr.",
  },
  {
    name: "Jisc Open Policy Finder",
    provides: "Publisher OA policies, the funder canon, and a repository list.",
    transport:
      "REST API with an x-api-key header and search_after paging, 0.15 seconds between requests by default.",
    usedBy: "Manual steps harvest_jisc and normalize_jisc.",
  },
  {
    name: "ip-api.com",
    provides: "Country codes for usage events.",
    transport: "Batch POST of up to 100 IPs, 4.5 seconds between calls on the free tier.",
    usedBy: "Manual step enrich_usage_geo.",
  },
  {
    name: "Pure portal (research.utwente.nl)",
    provides: "Organisation parents and person-org links the OAI feed lacks.",
    transport: "RSS pages fetched with a browser user agent, 2 seconds between requests.",
    usedBy: "Manual steps harvest_pure_portal and harvest_portal_persons.",
  },
  {
    name: "ut-metadata platform",
    provides: "Canonical works of the previous platform.",
    transport: "A read-only Postgres connection through JB_UT_METADATA_DSN. No HTTP requests.",
    usedBy:
      "Bootstrap step authors with --source utmd, one-time importers, and development checks.",
  },
  {
    name: "BAAI/bge-small-en-v1.5",
    provides: "384-dimension journal embeddings.",
    transport: "The model runs locally through fastembed and ONNX. No network requests.",
    usedBy: "Bootstrap step embeddings.",
  },
];
