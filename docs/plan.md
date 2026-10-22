# Implementation plan

Stack: FastAPI + SQLAlchemy 2 (async) + PostgreSQL 17 backend, Next.js (App Router,
TypeScript) frontend, Docker Compose, `uv` for Python. Harvest clients from the
bibliofabric family: **aletheca** (OpenAlex), **aireloom** (OpenAIRE),
**stavrophora** (Crossref); `ut-metadata` is the reference implementation for ingestion
patterns (see `docs/research/aletheca-ut-metadata.md`).

Global constraints:

- **Data window: publication years 2020 to now** on every works-derived query, stat, and
  table. Earlier data is out of scope until explicitly expanded.
- **Collect only**: register what sources natively publish; no derived metrics in v1.
- **Keyless first**: single-entity OpenAlex lookups (`W…`/`S…` ids) run without a key;
  the `OPENALEX_API_KEY` from the environment is used only for cursor-paged harvests.
- **Local copies always**: every harvester keeps raw payloads in the landing store
  permanently, independent of downstream normalization.
- **Limitations are data**: each source ships with registered caveats (see phase 6).

## Phase 0 — Foundations (skeleton in repo)

- [x] Repo layout, docker-compose (db/backend/frontend), FastAPI `/api/v1/healthz`,
      Next.js skeleton, `.env.example`, docs tree.
- [ ] Alembic wired; CI (ruff + pytest + frontend build).
- [ ] aletheca/aireloom/stavrophora as dependencies; a thin `harvest/common.py` with the
      ut-metadata `IngestSession` idiom (content-hash upserts, harvest_runs/harvest_state
      bookkeeping, per-page commits, per-record error isolation, type-check on yields).

## Phase 1 — Deal data model + ingestion (the core)

Data model (Postgres, alembic-managed):

- `publishers` (name, openalex host_organization id, openaccess.nl slug)
- `institutions` (name, ROR, openalex I-id; University of Twente = `006hf6230`, flagged)
- `deals` (publisher_id, esac_id, status current/archive, start/end dates,
  corresponding-authors-only, summary, conditions_text, workflow_text, cap text +
  per-year cap numbers, contract_url, openaccess_nl_url, per-year OA counts jsonb,
  provenance, last_reviewed)
- `deal_journals` (deal_id, issn_l, first/last seen, source: jct|manual)
- `deal_institutions` (deal_id, institution_id, first/last seen)
- `apc_evidence` (doi, period, euro, is_hybrid, agreement, group_id, issn_l, source:
  openapc; raw row reference) — OpenAPC TA rows for Twente (~297) and NL peers
- `manual_overrides` (table+field, value, rationale, set-by, set-at) — never overwritten
  by re-ingestion.

Jobs:

1. `ingest_jct`: TA index CSV → per-agreement Data CSVs → upsert deals, deal_journals
   (ISSN→ISSN-L), deal_institutions (ROR→institutions).
2. `scrape_openaccess_nl`: overview → publisher pages → deal pages; raw HTML to landing
   store + parsed structured fields; diff report on text changes.
3. `ingest_openapc`: download release CSVs (apc_de, transformative_agreements,
   contracts, additional_costs); store raw; aggregate to **journal-level evidence**
   (ISSN-L x period: typical APC, observed min/max, article counts) for every journal
   in the corpus, not just Twente rows; Twente/NL rows additionally land in
   `apc_evidence` as per-article records. Journal-level aggregates serve as fallback
   cost information wherever a deal gives no explicit price.
4. `reconcile`: match openaccess.nl deals ↔ JCT deals (publisher × duration); emit a
   curation report (HTML) of unmatched or conflicting rows (ACM local deals, non-Plan-S
   deals, OpenAPC agreements without JCT counterpart).

Acceptance: for each current openaccess.nl deal the DB shows a deal record with journal
list (or an explicit needs-curation flag), institutions, cap info, and source links;
verified against 5 known deals (Karger, Elsevier, OUP, PLOS, Thieme).

## Phase 2 — Journal harvest (OpenAlex via aletheca)

- `journals` table from OpenAlex `sources`: openalex id, issn_l, issns, title, publisher,
  type, is_oa, is_in_doaj, homepage, topics, apc_prices, summary_stats (as published,
  unmodified), counts_by_year, raw landing payload. Two routes per ut-metadata practice:
  seed from deal-covered ISSNs (`sources` lookups, keyless), then
  `session.sources.iterate` sweep for the browsable corpus.
- `apc_evidence` joined to journals by ISSN-L / DOI (`batch_get_by_doi`, 50/call).
- Scimagojr ingest: SJR + quartile per ISSN-L (yearly CSV), stored as published.
- OpenAIRE (aireloom) and Crossref (stavrophora) harvesters: per-journal enrichment
  passes (OA versions, license metadata); concrete field selection follows a first
  harvest, using `ut-metadata` harvesters as reference. No derived numbers from them.

Acceptance: sample journals (Water Research, PLOS ONE, a Twente-heavy journal) show
stats identical to the live OpenAlex source record; scimagojr quartile matches the CSV.

## Phase 3 — Institution statistics (2020+, collected only)

- `institution_works_stats` per journal x year: works count and OA-status counts from
  aletheca (`works_by_institution` + `primary_location.source.id` filters +
  `group_by=open_access.oa_status`), window `from_publication_date:2020-01-01`.
  Precomputed into tables (never per-request JSONB aggregation; ut-metadata lesson).
- Institution trend table: one yearly sweep for Twente totals (works per year, OA split).
- **Deferred (framework only, runs on your say-so)**: "cited by Twente staff" and
  co-citation "similar journals" via two-step W-id batching (collect journal work IDs,
  then `referenced_works` counts in batches of 100). The scaffold lands in phase 2 as a
  `harvest/journal_citations.py` stub with the batching helper, tests on a tiny sample,
  and a config flag default-off.

Acceptance: journal/year counts match live OpenAlex queries for a sample set.

## Phase 4 — Search API

`/api/v1/journals` — query (title/ISSN), facets: deal_coverage, is_oa, is_in_doaj,
topic, quartile; sorts: relevance, title, institution works, 2yr_mean_citedness;
keyset pagination. Postgres FTS on title + alternate titles; facets via filtered counts.
`/api/v1/journals/{issn_l}` — full detail bundle with per-field source attribution.
`/api/v1/deals`, `/api/v1/deals/{id}` — deal records with journal counts and evidence
links. `/api/v1/meta/limitations` — the caveat registry. OpenAPI auto-documented.

## Phase 5 — Frontend (Next.js)

- Home: search bar + facet chips + results list (title, publisher, deal badge, OA flag,
  Twente works count).
- Journal page: deal panel (cost implication for Twente authors, cap status, article
  types, workflow summary, links to openaccess.nl + contract PDF + JCT source), stats
  (per-year bars 2020+, OA split), metrics card with per-metric source labels, topics,
  OpenAPC evidence when present.
- Deals page: current deals with the structured openaccess.nl narrative.
- **Caveat hints**: a reusable `<SourceNote>` component rendering entries from the
  limitations registry inline wherever the related data appears; an About/data page
  listing all limitations.
- About: data sources, update cadence, disclaimers.

## Phase 6 — Green OA via Jisc Open Policy Finder (key pending)

- `harvest/jisc_opf.py` against `https://api.openpolicyfinder.jisc.ac.uk/retrieve`
  (`x-api-key`, `search_after` paging): per-journal policy records (versions, embargoes,
  licenses, conditions), raw JSON to landing store, normalized subset for display.
- Unblocks when Sam supplies the API key; scaffold can land earlier behind a flag.

## Phase 7 — Curation & ops

- Staff curation report (unmatched deals, stale data, scraper diffs), read-only HTML
  from the reconcile job.
- Scheduled jobs (compose service or cron) + freshness metadata per table in
  `/api/v1/meta/freshness` and the About page.
- Packaging pass for the open-source release: configurable institution (ROR + name in
  env), seed scripts, README walkthrough for a new university.

## Risks & mitigations

- **openaccess.nl drift**: scraper diffs + curation report; overrides survive re-runs.
- **OpenAlex quirks/regressions** (mailto deprecation, source-filter change, model
  coverage gaps): aletheca's quirks doc; type-check yields; live-marker tests.
- **Deal lists not in JCT**: explicit curation queue; honest "unknown" in the UI.
- **Metric expectations** (CiteScore/SJR habits): caveat hints state what each metric is
  and is not; no invented substitutes.
- **Green OA blocked on key**: phase 6 starts only when the Jisc key arrives.
