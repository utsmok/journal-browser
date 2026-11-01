# Harvest sources

Active contributors: utsmok

## Purpose

This page maps every external source to the adapter module that fetches it, the job that
runs it, and the tables it lands in. Fetch mechanics stay brief; the untracked deep-dives
under `docs/data-pipeline/` (`pure.md`, `openalex.md`, `deals.md`, `oa-status.md`,
`ut-metadata.md`) carry per-source traces, and the tracked
`docs/data-pipeline/OVERVIEW.md` holds live database numbers (queried 2026-10-29). To see
where each job sits in the graph, read [Bootstrap DAG](bootstrap-dag.md) first.

Jobs are CLIs in `backend/jobs/`; adapters live in
`backend/src/journal_browser/harvest/`. Every job stores verbatim payloads in
`source_records` (and file copies in `backend/landing/`) before normalizing, and writes a
`harvest_runs` row per run.

## Key abstractions

| Abstraction | Where | Role |
|---|---|---|
| `run_harvest()` | `backend/src/journal_browser/harvest/common.py` | Wraps a body in start-run, per-page commits, finish-run, cache-epoch bump. |
| `IngestSession` | `backend/src/journal_browser/ingest.py` | One run against one (source, entity type, filter set): verbatim storage, content-hash dedupe, parse-failure counting. |
| `store_raw_file()` | `backend/src/journal_browser/ingest.py` | File-level landing copy tracked in `raw_files`. |
| `issn_map` + `lookup_issn_l()` | `backend/src/journal_browser/models`, `backend/src/journal_browser/harvest/common.py` | Every ISSN variant resolves to its linking ISSN before joining to `journals`. |
| `refresh_*` SQL | `backend/src/journal_browser/harvest/denorm.py` | Denormalized journal and flag columns, shared by jobs and alembic backfills. |
| Org-tree closure | `backend/src/journal_browser/harvest/org_closure.py` | Affiliation rule: an org counts only if its chain reaches the institution root. |
| `needs_curation` | deal and deal-journal rows | Ambiguous data is flagged for the admin, never silently resolved. |
| `run_job()` | `backend/src/journal_browser/jobrunner.py` | Small CLI runner (--limit, one session) used by some job CLIs. |

## Source table

### OpenAlex: universe, stats, and works store

| Source | Provides | Module(s) | Job | Lands in |
|---|---|---|---|---|
| OpenAlex `sources` | The journal universe: ~177k journals (2026-10-29) keyed by ISSN-L, with OA flags, APC prices, topics, counts by year | `backend/src/journal_browser/harvest/openalex_journals.py` | `backend/jobs/harvest_journals.py` (global `journals`) | `journals`, `issn_map`, `source_records` |
| OpenAlex publisher lineage | Canonical top-level publisher per journal | `backend/src/journal_browser/harvest/publishers.py` | `backend/jobs/harvest_publishers.py` (global `publishers`) | `openalex_publishers`, `journals.publisher_canonical` |
| OpenAlex works filter | Per-institution works payloads and per-journal/year/OA statistics | `backend/src/journal_browser/harvest/institution_stats.py` | `backend/jobs/harvest_stats.py` (per-institution `stats`) | `source_records` (`works_stats`), `institution_works_stats`, `institution_trend` |
| OpenAlex works payloads | Normalized works store for the author path and journal works tabs | `backend/src/journal_browser/harvest/openalex_works.py` | `backend/jobs/build_openalex_works.py` (per-institution `openalex-works`) | `openalex_works` |

The sources sweep uses the `aletheca` client: keyless seed lookups for deal-covered ISSNs,
then a cursor-paged full sweep (keyed when `OPENALEX_API_KEY` is set). The works-store job
makes no API calls; it projects the latest stored payloads.

### Pure: OAI-PMH corpus and CERIF entities

| Source | Provides | Module(s) | Job | Lands in |
|---|---|---|---|---|
| Pure OAI-PMH publications | The canonical publications corpus per institution, with retirement on full re-baselines | `backend/src/journal_browser/harvest/pure/` (`transport.py`, `pipeline.py`, `store.py`) | `backend/jobs/harvest_pure.py` (steps `pure`, `pure-cerif`) | `works`, `source_records` |
| Pure CERIF ISSNs and author lists | Journal ISSNs per work and the per-work pure author list | `backend/src/journal_browser/harvest/pure/` (`cerif.py`, `entities.py`) | `backend/jobs/harvest_pure.py --cerif` (step `pure-cerif`) | `works` fields, `work_pure_authors` |
| Pure CERIF orgunits and persons | The org tree and the person roster the author path needs | `backend/src/journal_browser/harvest/pure/entities.py` | `backend/jobs/harvest_pure_entities.py` (step `pure-entities`) | `pure_orgs`, `pure_org_parents`, `pure_persons` |
| Pure portal organisations feed | Parent edges for orgs the OAI snapshot leaves parentless, plus type labels | `backend/src/journal_browser/harvest/pure_portal.py` | `backend/jobs/harvest_pure_portal.py` (manual, outside the DAG) | `pure_org_parents`, `pure_orgs.org_type`, `source_records` |
| Pure portal persons listings | Person-to-org bindings that fill roster gaps | `backend/src/journal_browser/harvest/pure_portal_persons.py` | `backend/jobs/harvest_portal_persons.py` (manual, reads relay-harvested JSON) | `pure_person_orgs`, `source_records` |

The OAI harvest is anonymous OAI-PMH 2.0: one `ListRecords` set per publication year with
resumption-token pagination; `--full-sweep` re-baselines and retires absent works. Both
portal jobs are gap-fill-only by contract: native CERIF resolution is never overridden, and
the portal feed must be fetched through a browser relay because the site WAF-blocks
scripted clients.

### Enrichment and confirmations

| Source | Provides | Module(s) | Job | Lands in |
|---|---|---|---|---|
| OpenAlex works by DOI | Rung 1: identity confirmation, `oa_status`, journal link | `backend/src/journal_browser/harvest/enrich.py` (`enrich_openalex`) | `backend/jobs/enrich_works.py` (step `enrich`) | `work_identity`, `works.oa_status`, `works.journal_issn_l` |
| Crossref | Rung 2: gap fill for DOIs OpenAlex does not know | `backend/src/journal_browser/harvest/enrich.py` (`enrich_crossref`) | same job | `work_identity`, journal links |
| Pure CERIF ISSNs | Rung 3: journal resolution from the harvest itself | `backend/src/journal_browser/harvest/enrich.py` (`resolve_journals_cerif`) | same job | `works.journal_issn_l` |
| OpenAIRE Graph v3 | DOI confirmations for local works | `backend/src/journal_browser/harvest/openaire.py` | `backend/jobs/harvest_openaire.py` (step `openaire`) | `work_identity`, `source_records` |

The ladder runs OpenAlex, then Crossref, then CERIF, always resolving journals through
`issn_map`. OpenAlex batches 50 DOIs per call with a pause between chunks; a batch rejected
with a client error is bisected so one bad DOI fails alone. OpenAIRE sweeps the Graph
filtered by the institution's `openaire_org_id` (a lookup stored on the institution row,
not derivable from the ROR); an unset id turns the harvest off for that institution.

### Deals

| Source | Provides | Module(s) | Job | Lands in |
|---|---|---|---|---|
| openaccess.nl | The canonical NL deal register: statuses, caps, contract narratives | `backend/src/journal_browser/harvest/openaccess_nl.py` | `backend/jobs/scrape_openaccess_nl.py` (global `deals-openaccess-nl`) | `deals`, `publishers`, landing HTML, `source_records` |
| JCT / ESAC dump (cOAlition S) | Agreement sheets, ESAC ids, journal lists | `backend/src/journal_browser/harvest/jct.py` | `backend/jobs/ingest_jct.py` (global `deals-jct`) | `deals`, `deal_journals`, `deal_institutions` |
| Both, merged | Deduplicated register and per-institution coverage | `backend/src/journal_browser/harvest/reconcile.py` | `backend/jobs/reconcile.py` (global `deals-reconcile`; per-institution `reconcile`) | `deals`, `deal_institutions.participation`, `journal_flags.deal_covered` |
| `issn_map` | ISSN-L resolution for coverage rows | `backend/src/journal_browser/harvest/issn_backfill.py` | `backend/jobs/backfill_issn_l.py` (global `deals-issn-l`) | `deal_journals.issn_l` |

The scrape walks overview, publisher, and deal pages and stores raw HTML in the landing
zone before parsing; admin `ManualOverride` rows win over scraped fields, with the
curation columns as the deliberate exception: `needs_curation` is harvest-owned, and an
admin dismissal is remembered in `deals.curation_resolved_reason` — the flag stays
cleared only while the page produces exactly that reason, and any other reason re-flags.
Reconcile merges candidates on `esac_id`, flags status conflicts as `needs_curation`, and
prints a curation report; it also treats a recorded dismissal as hand-ownership and will
not merge JCT rows into such a deal. With `--institution` it only derives participation
and refreshes coverage flags.
Unresolvable ISSNs keep `needs_curation` instead of being dropped.

### Journal metrics and derived flags

| Source | Provides | Module(s) | Job | Lands in |
|---|---|---|---|---|
| DOAJ | Gold/diamond canon: OA model truth, APC declarations, canon homepage | `backend/src/journal_browser/harvest/doaj.py` | `backend/jobs/harvest_doaj.py` (global `doaj`) | `journals.doaj_*` |
| OpenAPC | Observed APC costs per ISSN-L and period, plus per-article evidence | `backend/src/journal_browser/harvest/openapc.py` | `backend/jobs/ingest_openapc.py` (global `openapc`) | `journal_apc_aggregates`, `apc_evidence`, `journals.latest_apc_euro` |
| Scimago | SJR, best quartile, h-index | `backend/src/journal_browser/harvest/scimagojr.py` | `backend/jobs/ingest_scimagojr.py` (global `scimagojr`) | `scimagojr_metrics`, `journals.latest_quartile` |
| OpenAlex recent works | Observed OA color for venues with no other evidence | `backend/src/journal_browser/harvest/journal_oa.py` | `backend/jobs/harvest_oa_colors.py` (global `oa-colors`) | `journals.oa_status_observed` |
| `counts_by_year` (stored) | Derived activity flags for the corpus cutoff | `backend/jobs/backfill_flags.py` (self-contained SQL) | same file (global `flags`) | `journals.last_active_year`, `journals.works_2020_plus` |
| Shared refresh SQL | Denormalized columns and per-institution flag rows | `backend/src/journal_browser/harvest/denorm.py` | called by the jobs above | `journals`, `journal_flags` |
| Org-tree closure (helper) | Affiliation gating for entities and authors, not a source | `backend/src/journal_browser/harvest/org_closure.py` | none | in-memory `OrgTree` |

DOAJ ships as one bulk CSV from `doaj.org/csv` that lands verbatim; after a successful
parse, unmatched OA candidates are stamped `doaj_in_doaj = false` so NULL always means
never-swept. OpenAPC re-reads its landed release CSVs on every normalization pass. Scimago
cannot be downloaded by script (Cloudflare), so `backend/jobs/ingest_scimagojr.py`
materializes the tracked seed CSVs in `backend/data/scimagojr/` into the landing zone. The
OA-color sampler reads the 20 most recent works per candidate venue, stores the modal
non-green color, and fills NULLs only.

### Author path

| Source | Provides | Module(s) | Job | Lands in |
|---|---|---|---|---|
| OpenAlex authors listing | Institution authors (ROR-filtered) plus budget-capped per-author works sweeps | `backend/src/journal_browser/harvest/author_ids.py` | `backend/jobs/resolve_author_ids.py` (step `author-ids`) | `author_identities`, `openalex_works`, `source_records` |
| Local stores (works, CERIF, cascade) | Work-anchored identity resolution, no DSN needed | `backend/src/journal_browser/harvest/author_cascade.py`, `backend/src/journal_browser/harvest/author_names.py` | same job | `author_identities` |
| Author roster ingest | `authors` and `author_works` from the selected source adapter | `backend/src/journal_browser/harvest/authors.py` | `backend/jobs/ingest_authors.py` (step `authors`) | `authors`, `author_works` |
| ut-metadata DSN (optional) | Canonical works, verbatim records, and the author roster behind `author_source=utmd` | `backend/jobs/import_utmetadata_works.py`, `backend/jobs/import_utmetadata_raw.py`, `backend/jobs/verify_utmetadata.py` | manual one-shot imports, not in the DAG | `works`, `source_records`, `authors`, `author_works` |

The cascade is deterministic per work: `orcid-exact`, `name-exact`, `name-initials`,
`family-unique`, `name-fuzzy-strict`, with cross-work aggregation ranking methods and
counting conflicts. Results are `confirmed`, `candidate`, or `rejected`; candidates never
auto-promote and admin review decisions are sticky. The roster ingest defaults to
`fetch_local_source` (journal-browser's own tables); the `utmd` source needs the
per-institution or global ut-metadata DSN.

### Scaffolds (gated OFF)

| Source | Provides | Module(s) | Job | Lands in |
|---|---|---|---|---|
| Jisc Open Policy Finder | Green-OA policies | `backend/src/journal_browser/harvest/jisc_opf.py` | none wired; requires `JB_ENABLE_JISC` and `JB_JISC_API_KEY` | none (zero calls while OFF) |
| OpenAlex citations | "Cited by Twente staff" counts | `backend/src/journal_browser/harvest/journal_citations.py` | none wired; requires `JB_ENABLE_JOURNAL_CITATIONS` | none |

Both scaffolds make zero calls while their flags are off. The similar-journal feature that
citation counts would have fed shipped via embeddings instead (see
[Design decisions](../../background/design-decisions.md)).

## How it works

All jobs share one shape: resolve the institution (or none for global jobs), open a
session, wrap the body in `run_harvest()`, land raw data, normalize with upserts or
full-replace projections, commit per page, and close the run. Which jobs run, and in what
order, is decided by the DAG: see [Bootstrap DAG](bootstrap-dag.md).

## Integration points

- Environment levers in `docker-compose.yml` and `backend/src/journal_browser/config.py`:
  `OPENALEX_API_KEY`, `JB_PURE_OAI_BASE_URL`, `JB_OPENAIRE_ORG_ID`, `JB_UT_METADATA_DSN`,
  and the two scaffold flags.
- The admin panel curates what jobs must not overwrite: deal `ManualOverride` rows and the
  author-identity review queue (`backend/src/journal_browser/routers/admin/`).
- Every successful harvest calls `bump_cache_epoch`, which invalidates the serving caches
  described in [Search](../search.md).
- `backend/landing/` doubles as an operations surface: curation reports land in
  `backend/landing/reports/`, and Scimago exports must be placed there manually.

## Entry points for modification

- Add a source: write the adapter in `backend/src/journal_browser/harvest/`, a CLI in
  `backend/jobs/`, and wire the job into the DAG (see [Bootstrap DAG](bootstrap-dag.md)).
- Re-parse without re-fetching: adapters must read from `source_records` or the landing
  zone, so changing a parser never requires new downloads.
- Tune classification inputs: DOAJ, OpenAPC, Scimago, and OA colors all denormalize onto
  `journals` through `backend/src/journal_browser/harvest/denorm.py`; refresh functions
  there are shared with alembic backfills and must stay in one place.

## Key source files

| File | Role |
|---|---|
| `backend/src/journal_browser/harvest/common.py` | Run wrapper, ISSN and DOI normalization, HTTP retry, institution helpers. |
| `backend/src/journal_browser/ingest.py` | `IngestSession`: verbatim storage, dedupe, run lifecycle. |
| `backend/src/journal_browser/models/harvest.py` | `harvest_runs`, `harvest_state`, `source_records`, `raw_files`. |
| `backend/src/journal_browser/harvest/denorm.py` | Shared denormalization SQL for journals and journal_flags. |
| `backend/src/journal_browser/jobrunner.py` | Minimal CLI runner for job entry points. |
| `docs/data-pipeline/OVERVIEW.md` | Tracked per-source overview with live database numbers (2026-10-29). |

## Related pages

- [Bootstrap DAG](bootstrap-dag.md) orders these jobs into the deployment pipeline.
- [Data model](../data-model.md) documents the target tables listed above.
- [Search](../search.md) covers what serving reads once harvest lands.
- [Tooling](../../how-to-contribute/tooling.md) for running jobs locally.
- [Architecture](../../overview/architecture.md) for the deployment view.
