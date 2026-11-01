# Data pipeline

Active contributors: utsmok

## Purpose

The pipeline turns a fresh database into a fully stocked one with a single command. A one-shot
compose service runs `backend/jobs/bootstrap.py`, which executes every harvest job as a
dependency DAG in two layers:

1. **Global layer**: institution-neutral data built once per deployment. This is the shared
   core: the OpenAlex journal universe, the deal register, OpenAPC and Scimago metrics, DOAJ
   canon, OA-color observations, and derived journal flags.
2. **Per-institution layer**: runs once for every hosted institution code (for example `ut`
   and `rug`). Each institution gets its own Pure works corpus, CERIF entities, enrichment
   ladder, OpenAIRE confirmations, statistics, and author path. See
   [Multi-institution](../../features/multi-institution.md) for why the layering exists.

The layers matter for onboarding: adding an institution means inserting one `institutions`
row and running the bootstrap with `--institution <code>`, which skips the global layer
entirely.

## The backend stays down until success

`docker-compose.yml` gates the backend on the bootstrap service:

- The `bootstrap` service runs `alembic upgrade head` and then
  `python jobs/bootstrap.py`, with `restart: "no"`.
- The `backend` service declares `depends_on: bootstrap: condition:
  service_completed_successfully`, so a failed or half-finished harvest never serves traffic.
- In the default `auto` mode (`JB_BOOTSTRAP`), a bootstrap pass over a database that already
  has journals exits in seconds, so every `docker compose up` re-runs it harmlessly.

A failure therefore stops new steps, names the failed steps in the logs, and leaves the
database unfilled but consistent. That is deliberate: a half-filled database is never served.

## Idempotency contract

Every step is a standalone idempotent job that can be re-run alone:

- Raw payloads land verbatim before any normalization, so re-parses never re-fetch.
- Writes are upserts, content-hash-deduped versioned rows, or full-replace projections.
- Each successful harvest bumps the cache epoch (`bump_cache_epoch` in
  `backend/src/journal_browser/harvest/common.py`), invalidating epoch-keyed serving caches.
- Jobs fail by naming their step; a failed run commits what already landed per page, then
  re-raises.

## Landing zone

Downloaded artifacts (CSVs, HTML, feed pages) land in `backend/landing/` before parsing.
Compose bind-mounts `./backend/landing` into the containers so raw copies and job logs
survive rebuilds. File-level copies are tracked in the `raw_files` table and record-level
payloads in `source_records` (see `backend/src/journal_browser/models/harvest.py`). Some
sources only exist through this zone: Scimago exports must be placed there manually because
scimagojr.com blocks scripted downloads, and the Pure portal feeds were relay-harvested
through a browser.

## Run bookkeeping

`backend/src/journal_browser/models/harvest.py` defines the bookkeeping tables:

- `harvest_runs`: one row per run (source, entity type, optional institution, status,
  config fingerprint, JSONB stats). The admin panel's runs pages inspect them.
- `harvest_state`: latest status per (source, entity type, filter set) key.
- `source_records`: verbatim payloads, versioned by content hash.
- `raw_files`: file-level landing copies.

The `run_harvest` wrapper in `backend/src/journal_browser/harvest/common.py` opens the run,
executes the harvest body with per-page commits, closes the run as `completed` or `failed`,
and bumps the cache epoch. Only the run's own process can close it: a killed job would leave
the row `running` forever. Every `start_run` therefore first closes stale `running` rows of
the same `(source, entity_type, institution)` key, marking them `failed` with a
`stale: superseded` marker in their stats, so a crash cannot leave a phantom run and an
accidental overlap is visible in the runs table instead of pretending both runs completed.

## Repairing a run

Three flags cover recovery without touching code:

| Flag | Effect |
|---|---|
| `--from STEP` | Resume mode: run serially from that step onward (see [Bootstrap DAG](bootstrap-dag.md)). |
| `--institution CODE` | Run only that institution's layer, skipping the global layer and embeddings. |
| `--always` | Force a full run even when `auto` mode would skip a bootstrapped database. |

## Directory layout

| Path | Role |
|---|---|
| `backend/jobs/` | One CLI per job plus `bootstrap.py`, the DAG runner. |
| `backend/src/journal_browser/harvest/` | Source adapters, one module per external source. |
| `backend/landing/` | Raw landing zone (gitignored content volume). |
| `backend/src/journal_browser/models/harvest.py` | Run, state, and verbatim-store tables. |
| `docker-compose.yml` | The one-shot `bootstrap` service and the backend gating. |

## In this section

- [Bootstrap DAG](bootstrap-dag.md): the step graph, dependencies, runners, and compose wiring.
- [Harvest sources](harvest-sources.md): source-by-source map of what each external source
  provides and which module and job ingest it.

## Related pages

- [Architecture](../../overview/architecture.md) places the pipeline inside the deployment.
- [Data model](../data-model.md) documents the tables the pipeline writes.
- [Design decisions](../../background/design-decisions.md) records why jobs are idempotent
  and why the backend waits.
