# Data models

The serving schema is defined by SQLAlchemy 2 declarative models in
`backend/src/journal_browser/models/`; `models/__init__.py` is the registry
every import goes through. This page is the terse table-by-table reference.
For how the layers fit together, why search state is denormalized, and how
identity and curation state survive re-harvesting, read
[Data model](../systems/data-model.md).

Conventions across all tables: plain `Text` columns with `CheckConstraint`
vocabularies instead of pg enums, soft Pure uuids as text rather than
foreign keys in the CERIF layer, and partial unique indexes wherever a key
column is nullable.

Migrations live in `backend/alembic/versions/` (43 files, head
`0042_pure_person_orgs`). They are historical record and never reformatted,
and CI requires that every migration downgrades cleanly on a test database.

## Shared core

Institution-neutral tables harvested once per deployment and served to
every hosted institution.

| Table | Model (file) | Purpose | Key columns and constraints |
|---|---|---|---|
| `journals` | `Journal` (`journals.py`) | One row per journal, ISSN-L-keyed; normalized OpenAlex source plus denormalized DOAJ/OpenAPC/Scimago flags. | PK `issn_l`; `search_vector` generated TSVECTOR; `embedding` `Vector(384)`; denorm columns `latest_quartile`, `latest_apc_euro`, `oa_status_observed`, `doaj_*`, `works_2020_plus`. |
| `scimagojr_metrics` | `ScimagojrMetric` (`journals.py`) | SJR, quartile, and h-index per ISSN-L and year, stored as published. | PK (`issn_l`, `year`). |
| `publishers` | `Publisher` (`reference.py`) | Canonical publisher names with OpenAlex and openaccess.nl cross-links. | Unique `name`, unique `openaccess_nl_slug`. |
| `openalex_publishers` | `OpenalexPublisher` (`reference.py`) | OpenAlex publisher lineage cache; canonical name is the lineage root. | PK `openalex_id`; NULL `lineage` marks a failed fetch so re-runs skip it. |
| `issn_map` | `IssnMap` (`reference.py`) | ISSN to ISSN-L resolution index, harvested from OpenAlex sources. | PK `issn`. |
| `institutions` | `Institution` (`reference.py`) | The multi-institution pivot: one row per real institution; hosted rows carry `code` plus `active`. | Unique `code`, unique `ror`; data window columns; display URLs; `require_confirmed_affiliation`. |
| `deals` | `Deal` (`deals.py`) | Open-access agreements from the openaccess.nl register with JCT/ESAC enrichment. | Unique `esac_id`; `status` CHECK (`current`/`archive`); `needs_curation` reason CHECK. |
| `deal_journals` | `DealJournal` (`deals.py`) | Journal coverage per deal. `institution_id` NULL rows are the shared sheet list; set rows are per-institution overrides. | `source` CHECK (`jct`/`manual`/`publisher-pattern`); partial unique indexes split shared vs scoped rows; `excluded` rows survive JCT re-upserts. |
| `deal_institutions` | `DealInstitution` (`deals.py`) | Deal-institution partnership; a missing row means non-participation. | PK (`deal_id`, `institution_id`); `participation` CHECK (`named`/`consortium`); `journal_override`. |
| `apc_evidence` | `ApcEvidence` (`evidence.py`) | Per-article APC/TA cost rows (OpenAPC) for Twente and NL deal institutions. | `source_record_id` FK for provenance; indexed on (`issn_l`, `period`). |
| `journal_apc_aggregates` | `JournalApcAggregate` (`evidence.py`) | Journal-level cost evidence: ISSN-L by period aggregates of OpenAPC rows. | PK (`issn_l`, `period`). |
| `limitations` | `Limitation` (`app_data.py`) | Registered data caveats per source and scope, surfaced in the UI. | `severity` CHECK (`info`/`warning`). |

## Per-institution

Every row is scoped by `institution_id`; most carry `ondelete="CASCADE"`
from `institutions`.

| Table | Model (file) | Purpose | Key columns and constraints |
|---|---|---|---|
| `journal_flags` | `JournalFlags` (`journals.py`) | Fully materialized per-institution journal state for search and facets. | PK (`institution_id`, `issn_l`); `works_count`, `deal_covered`, `works_window_plus`, `browse_excluded`. |
| `works` | `Work` (`works.py`) | Canonical institution works harvested from Pure via OAI-PMH. | PK (`institution_id`, `pure_uuid`); `oa_status` CHECK (six colors); partial unique DOI per institution. |
| `work_identity` | `WorkIdentity` (`works.py`) | Cross-source record to work links (OpenAlex/OpenAIRE confirmations and candidates). | Unique (`institution_id`, `source`, `source_pk`); `matched_by` CHECK (`doi`/`verbatim`/`trgm:...`); composite FK to `works`. |
| `pure_orgs` | `PureOrg` (`pure.py`) | Orgunits of the institution's Pure org tree (CERIF). | PK (`institution_id`, `uuid`); `identifiers` JSONB keeps the ROR. |
| `pure_org_parents` | `PureOrgParent` (`pure.py`) | Parent edges of the org tree; parent may be absent at harvest time. | Composite FK to `pure_orgs`. |
| `pure_persons` | `PurePerson` (`pure.py`) | Person roster with the parsed CERIF payload under `{"cerif": ...}`. | PK (`institution_id`, `uuid`); partial index on ORCID. |
| `pure_person_orgs` | `PurePersonOrg` (`pure.py`) | Person-to-org bindings relay-harvested from the Pure portal listings; gap-fill evidence only. | Composite FKs to `pure_persons` and `pure_orgs`; `listing_kinds` JSONB. |
| `work_pure_authors` | `WorkPureAuthor` (`pure.py`) | Pure's own author list per work, with work-level affiliation orgs and name spellings for the identity cascade. | Composite FK to `works`; indexed on person. |
| `openalex_works` | `OpenalexWork` (`openalex.py`) | Normalized OpenAlex works store for the institution's population; compact `authorships` JSONB. | PK (`institution_id`, `w_id`); `oa_status` CHECK; DOI index intentionally non-unique (merged W-ids). |
| `author_identities` | `AuthorIdentity` (`openalex.py`) | External identity proposals and admin decisions; durable state that survives roster re-ingestion. | PK (`institution_id`, `author_pure_uuid`, `source`, `external_id`); `status` CHECK (`confirmed`/`candidate`/`rejected`); `source` CHECK (`openalex`/`openaire`). |
| `authors` | `Author` (`authors.py`) | Researcher roster with derived faculty, research group, and institute. | PK (`institution_id`, `pure_uuid`); `openalex_ids` JSONB (primary plus merged ids); `confirmed` marks ROR-resolving affiliation. |
| `author_works` | `AuthorWork` (`authors.py`) | Author to work membership edges; full-replace per institution at ingest. | Composite FKs to `authors` and `works`. |
| `institution_works_stats` | `InstitutionWorksStats` (`evidence.py`) | Per journal-year works counts and OA split, precomputed. | PK (`institution_id`, `source`, `issn_l`, `year`). |
| `institution_trends` | `InstitutionTrend` (`evidence.py`) | Institution-wide yearly totals with OA split and corresponding-author counts. | PK (`institution_id`, `year`). |

## Bookkeeping and app data

Harvest bookkeeping, the landing store, and app-owned state.

| Table | Model (file) | Purpose | Key columns and constraints |
|---|---|---|---|
| `harvest_runs` | `HarvestRun` (`harvest.py`) | One row per job run with stats and a config fingerprint. | `status` CHECK (`running`/`completed`/`failed`); `institution_id` NULL means a global job. |
| `harvest_state` | `HarvestState` (`harvest.py`) | Durable per-job status used for resume and `--from` repair. | Partial unique indexes keep one row per key for global and institution-scoped jobs separately. |
| `source_records` | `SourceRecord` (`harvest.py`) | Landing store: verbatim payloads, content-hash versioned, append-only. | Unique (`source`, `entity_type`, `source_pk`, `content_hash`); mirrored `publication_year` column for window filtering. |
| `raw_files` | `RawFile` (`harvest.py`) | File-level landing copies of downloaded artifacts. | Same unique version key as `source_records`. |
| `cache_epoch` | `CacheEpoch` (`app_data.py`) | One-row harvest counter; in-process caches key on `bumped_at` so any harvest step invalidates them across processes. | Single row, bumped by harvest and denorm refreshes. |
| `manual_overrides` | `ManualOverride` (`app_data.py`) | Curated values that re-ingestion must never overwrite; survives every replay. | Unique (`table_name`, `row_key`, `field`). |
| `feedback_items` | `Feedback` (`app_data.py`) | User-reported issues with the frontend's Query-cache dump attached as `page_data`. | CHECK constraints on `status`, `priority`, `category`. |
| `doc_edits` | `DocEdit` (`app_data.py`) | Admin replacement blocks for served markdown docs, applied at read time. | Unique (`doc_slug`, `block_key`). |

## Related pages

The explanatory schema tour is [Data model](../systems/data-model.md); the
jobs that fill these tables are in
[Data pipeline](../systems/data-pipeline/index.md), and the admin surfaces
that edit curation state are in [Admin](../features/admin.md).
