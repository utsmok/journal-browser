# Research: aletheca and ut-metadata

Mined 2026-10-22 from local checkouts (aletheca v0.2.2, MIT, PyPI; ut-metadata).

## 1. aletheca — OpenAlex client on bibliofabric

Async OpenAlex client, thin layer over `bibliofabric` 0.5.x. Python >= 3.12, pydantic v2,
`py.typed`.

- Exports `AlethecaClient`, `AlethecaSession`, 9 entity models, bibliofabric exceptions.
- `AlethecaClient(BaseApiClient)` with lazy resource properties: `works, authors, sources,
  institutions, topics, keywords, publishers, funders, awards` (`src/aletheca/client.py`).
  Auth resolved once: `QueryParameterAuth(key_name="api_key")` when a key is configured,
  else `NoAuth`.
- `AlethecaSession` async context manager delegates the 9 resources plus a
  `session.queries.*` accessor that partial-binds convenience functions
  (`works_by_author`, `works_by_institution`, `works_by_doi`, `citing_works`,
  `referenced_works`; `src/aletheca/queries.py`).
- Standard resource client (`src/aletheca/resources/_standard.py`): OpenAlex param names,
  `filter=key:value,key:value` serialization, `BATCH_GET_SIZE = 50`, `get()` normalizes
  full-URL/slug ids, and declaring `_batch_fields` auto-generates `batch_get_by_<field>()`
  methods (`WorksClient._batch_fields` = doi, openalex, pmid, pmcid, mag). Mixins give
  `get / search / iterate` (cursor pagination) plus `collect() / count() / first()`.
- Pydantic filter models with dot-notation aliases and `extra="allow"` for all entities
  (`src/aletheca/endpoints.py`).
- Models: `Work, Author, Source, Institution, Topic, Keyword, Publisher, Funder, Award`
  plus `ApiResponse[Entity]`, common types (`Location`, `OpenAccess`, `Biblio`),
  dehydrated entities, and `SafeList`/`SafeStr` None-safe traversal.
- Config: pydantic-settings, `ALETHECA_` env prefix, loads `.env`/`secrets.env`;
  `openalex_api_key` optional (`src/aletheca/config.py`).
- Documented limitations: OpenAlex model coverage incomplete (see `OPENALEX_BUG_REPORT.md`),
  `per_page` max 100, keyword ids are slug paths normalized inside `get()`, awards
  valid-filter discovery only via the 400 body, and no incremental updates on the free
  tier (`from_updated_date` is paid).

## 2. ut-metadata — UT scholarly-metadata platform

Harvests Pure (OAI-PMH), OpenAlex (aletheca 0.2.2), OpenAIRE (aireloom 0.5.2), Crossref
(stavrophora 0.2.1) into Postgres 17; reconciles across sources; read-only FastAPI plus a
Chrome side-panel extension. Stack: SQLAlchemy 2.0 async + Alembic (migrations 0001-0034)
+ psycopg 3, Docker Compose. Direct architectural overlap with this project.

- Storage: canonical entities (`work, person, org, funder, venue, project, award`) +
  verbatim `source_records` (JSONB payload, `content_hash`,
  `UNIQUE(source, entity_type, source_pk, content_hash)`, versioned append) +
  `source_identity` linkage (`matched_by`, confidence) + `harvest_state` checkpoints +
  `harvest_runs` per-run stats/config fingerprint.
- Harvesters (`src/ut_metadata/harvest/`): one module per source and strategy;
  `openalex.py` (institution-filtered `iterate()` full refresh, `on_page` commit,
  yields type-checked because bibliofabric falls back to raw `dict` on parse failure),
  `openalex_dois.py` (DOI-driven `batch_get`, 50/call, 0.1 s pacer),
  `openalex_entities.py` (fan-out from stored work payloads to linked entities),
  `openaire*.py`, `crossref*.py`, `pure*.py`, `orcid_records.py`,
  `openaire_venues.py` (OpenAIRE has no venue endpoint; venues mined per-work).
- Ingest core: `IngestSession` idiom with content-hash versioned upserts, per-page
  commits, per-record error isolation, run-level tripwires, NUL-byte stripping for JSONB
  (`src/ut_metadata/ingest.py`).
- Derived read structures rebuilt by `refresh_derived`: materialized latest-records view,
  trigram name pools, entity-to-work edge tables. Per-request aggregation over 422k JSONB
  rows measured 7-11 s; edge joins serve in ms.

## 3. Reusable patterns for the journal browser

- Copy the ut-metadata ingestion core: content-hash versioned upserts, harvest bookkeeping
  tables, per-page commits, per-record error isolation.
- Journals = OpenAlex `sources`. Two proven routes: direct
  `session.sources.search/iterate` with `SourcesFilters`, or fan-out from a works corpus
  (mine `primary_location/locations[].source.id`, then `sources.batch_get`).
- Precompute statistics; never aggregate JSONB per request. Rebuild owned derived tables
  behind the API.
- `batch_get_by_doi()` (50-cap) is the pattern for DOI-driven enrichment (OpenAPC rows).
- Fix client gaps upstream in aletheca/bibliofabric; never shim locally.

## 4. Copy / avoid callouts

- Copy: `ALETHECA_*`-style pydantic-settings auth; filter models with dot-notation
  aliases; canonical-id + verbatim-record store (re-harvests are free).
- Avoid: relying on bibliofabric cursor persistence (restart per set only); trusting
  yields are always models; OpenAlex incremental sync (paid; full refresh is cheap,
  about 836 pages); `per_page` > 100; per-request JSONB aggregation; stacking client
  retries on a custom pacer without a pacing budget (Crossref list routes cap 3 rps).
