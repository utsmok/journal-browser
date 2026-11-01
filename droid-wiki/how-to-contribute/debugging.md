# Debugging

A runbook for the failures you are most likely to meet: a harvest step dying, a stale-looking API response, or an API status code that surprises you. The pipeline's structure is described in [the bootstrap DAG page](../systems/data-pipeline/bootstrap-dag.md).

## Pipeline failures

The bootstrap service runs every job as one DAG. Jobs are idempotent and fail by naming their step, so the first place to look is the service log:

```
docker compose logs -f bootstrap
```

A failure stops new steps from starting but lets already-running steps finish; the log names the failed steps. Restart the pipeline from a known step in repair mode:

- `--from STEP` resumes serially in topological order from the named step (names are in `backend/jobs/bootstrap.py` under `GLOBAL_STEPS` and `INST_STEPS`).
- `--institution CODE` runs only that institution's layer; onboarding a new institute is one institutions row plus `--institution <code>`.
- `--always` forces a full rerun when auto mode would skip (it skips whenever journals already exist).

Run these via `cd backend && uv run python jobs/bootstrap.py ...` against your test stack, not the live one.

## Inspecting harvest runs

Every step records a row in `harvest_runs` (model in `backend/src/journal_browser/models/harvest.py`): `source`, `institution_id`, `status` (`running`, `completed`, or `failed`), `started_at`, `finished_at`, and a `stats` payload. `harvest_state` keeps the latest status per source.

Caveat: a hard-killed process leaves its row at `running` forever. Nothing heals stale rows, so judge by `started_at` age and `finished_at IS NULL` rather than by status alone:

```sql
SELECT source, status, started_at, finished_at
FROM harvest_runs ORDER BY id DESC LIMIT 20;
```

On the live system, the admin panel shows the same data through `GET /api/v1/admin/runs` (password-gated). Remember the live `journalbrowser` database is SELECT-only for agents.

## Quick health and artifact checks

- `curl http://localhost:8000/api/v1/healthz` runs a `SELECT 1` and returns the app version; if this fails, the backend or database is down rather than a step in the pipeline.
- `backend/landing/` holds the raw downloaded source artifacts (compose bind-mounts it; the test stack uses `backend/landing-test`). The `raw_files` table indexes them.
- `backend/logs/` holds ad-hoc log files from long-running local jobs; the compose services log to stdout instead.

## Reproducing without touching live

Use the test stack from [development workflow](development-workflow.md): `docker compose -p jb-test -f docker-compose.yml -f compose.test.yml up -d --build` boots a fresh deployment on db 5533, backend 8001, frontend 3001, with the publication window pinned to 2025. For unit-level work, the pytest harness in [testing](testing.md) creates a throwaway database per process.

## Common gotchas

- ValueError maps to 400, not 422. Malformed query input (cursors, scoping) raises `ValueError` in service code, and an app-level handler in `backend/src/journal_browser/main.py` returns HTTP 400. FastAPI's own request validation returns 422. A 400 means a domain-level rejection; a 422 means the parameter failed schema validation.
- Route precedence. The admin, feedback, and docs routers register before the `/{institution_code}` catch-all, so `/api/v1/admin/runs` is never parsed as institution `admin`. Changing router registration order in `backend/src/journal_browser/main.py` breaks this; `backend/tests/test_route_precedence.py` guards it.
- `cache_epoch` staleness. Search facets and publisher snapshots cache under a key that includes `cache_epoch` (see `backend/src/journal_browser/services/cache.py`), and harvests bump the epoch. If you mutate rows directly in the database, cached API responses stay stale until the epoch bumps or the backend restarts. After a harvest, staleness usually means the bumping step did not run; rerun from it with `--from`.
