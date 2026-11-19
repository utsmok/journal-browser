# Multi-institution hosting

One deployment serves several universities at `/{code}/...` paths (for
example `/ut` and `/rug`), with a landing chooser at `/`. This shipped on
2026-10-24 and has run in production since: the live stack hosts the
University of Twente and Rijksuniversiteit Groningen side by side.
`backend/tests/test_multi_institution.py` covers the scoping rules.

The design goal: a second university costs one SQL `UPDATE` plus one
harvest run. Everything a university shares with the others is stored once;
everything specific to it is keyed by its institutions row. Onboarding is
documented in "Adding a second institution" in
[DEPLOYMENT.md](../DEPLOYMENT.md).

## What is shared, what is per institution

Stored once for the whole deployment:

- The journal universe and its flags, quartiles, and embeddings.
- The NL deal register: `deals`, `deal_journals`, JCT and openaccess.nl
  sheet data, deal identity reconciliation.
- OpenAPC evidence and Scimago data.
- Usage tracking events.

Stored per institution (every table and API route is scoped by it):

- The works corpus (`works`, `work_identity`) and the harvests that build
  it: Pure OAI sweep, enrichment, OpenAIRE.
- Statistics, trends, and participation in each deal.
- The publication-year data window, applied to stats, browse visibility,
  and trend charts.
- Author identity resolution and the author roster.

## The institutions row

The `institutions` table holds every university that openaccess.nl lists
as a deal participant; those rows are inactive and have no code. A hosted
institution is a row with `code` set and `active = true`, served at
`/{code}/...`. The row is the only configuration carrier: harvest sources,
data window, and display fields all come from columns, not env vars.

| Column | Meaning |
|---|---|
| `code` | URL segment (`ut`, `rug`); unique; NULL = not hosted |
| `name`, `short_name` | Display name and abbreviation |
| `ror` | ROR id, unique; identifies the institution to harvests |
| `openalex_id` | OpenAlex institution id |
| `pure_oai_base_url` | The institution's Pure OAI endpoint |
| `openaire_org_id` | OpenAIRE OpenOrgs id for the works harvest |
| `external_works_dsn` | Optional read-only DSN to an external canonical-works Postgres (see "Still UT-specific") |
| `data_window_start`, `data_window_end` | Inclusive publication-year window; start defaults to 2020, a NULL end is open to now (Groningen runs 2025 only) |
| `library_url`, `oa_guide_url`, `support_email`, `admin_contact`, `research_portal_url` | Display fields, served to the frontend via `/meta/freshness` |
| `active` | Hosted and served at `/{code}` |
| `require_confirmed_affiliation` | When true, author search lists only authors whose Pure affiliation resolves to this institution's ROR |

Env vars (`JB_INSTITUTION_NAME`, `JB_PURE_OAI_BASE_URL`,
`JB_OPENAIRE_ORG_ID`, and friends) seed the home institution's row once,
during migration 0019. After that the table is authoritative: changing an
env var never updates an existing row. The home institution resolves by
ROR match against `JB_INSTITUTION_ROR`, not by a flag column.

## Harvest layers

`backend/jobs/bootstrap.py` runs a two-layer DAG:

- **Global layer**, once per deployment: journals sweep, openaccess.nl
  scrape, JCT ingest, deal reconcile, ISSN-L backfill, OpenAPC, Scimago,
  OA colors, DOAJ, journal flags.
- **Per-institution layer**, run for every hosted code: Pure OAI sweep and
  CERIF entities, works enrichment, OpenAIRE and derived facts, statistics,
  participation reconcile, the OpenAlex works store, Pure author backfill,
  author identity resolution, author ingest.
- Embeddings are institution-neutral and run once, after the stats layers.

`--institution <code>` runs only that institution's layer, which is why
onboarding needs no global rerun.

## Still UT-specific

Three pieces are UT-only. A new institution works without them; they are
the remaining cleanup candidates:

- `jobs/harvest_people_utwente.py` sweeps the people.utwente.nl staff
  profile site (hardcoded URLs) into the `people_utwente_persons` and
  `people_utwente_orgs` tables.
- `jobs/harvest_pure_portal.py` and `jobs/harvest_portal_persons.py`
  scrape the research.utwente.nl Pure portal to fill missing org-tree
  edges and person listings.
- The ut-metadata accelerator: `external_works_dsn` is a generic column,
  but only UT has such a database. `jobs/import_utmetadata_works.py` and
  `jobs/import_utmetadata_raw.py` are one-shot imports from it.

The Pure OAI harvest itself (`jobs/harvest_pure.py`) is not UT-specific:
it reads `pure_oai_base_url` from the institution row, which is how
Groningen harvests.
