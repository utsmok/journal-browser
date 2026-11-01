# How to monitor

The repo has logging and database-based observability. It has no metrics,
tracing, or alerting infrastructure, and this page does not pretend
otherwise: the monitoring story is container health checks, the
`harvest_runs` table, and logs. If you want a one-line operating recipe, it
is: watch `docker compose ps`, read `docker compose logs`, and query the
runs table.

## The health endpoint

`GET /api/v1/healthz` (`backend/src/journal_browser/main.py`) executes
`SELECT 1` through the normal async session and returns
`{"status": "ok", "version": ...}`. It proves two things: the app is up and
the database is reachable. It says nothing about harvest freshness; use
`GET /api/v1/meta/freshness` for that (see below).

## Compose health checks

`docker-compose.yml` defines a check per service:

| Service | Check | Cadence |
|---|---|---|
| db | `pg_isready -U journal -d journalbrowser` | every 5 s |
| backend | Python `urllib` GET of `http://127.0.0.1:8000/api/v1/healthz` | every 30 s |
| frontend | `wget` of `http://127.0.0.1:3000/` | every 30 s |

Startup ordering builds on these: the backend waits for a healthy db and a
successfully completed `bootstrap` service, and the frontend waits for a
healthy backend. A failed bootstrap therefore keeps the API down by design,
with the reason in `docker compose logs bootstrap`. `docker compose ps` is
the first check on any incident; the health column tells you which layer
broke.

## Harvest observability

The pipeline monitors itself by writing rows. Every job run inserts a
`harvest_runs` row (`backend/src/journal_browser/models/harvest.py`):
source, entity type, optional institution, `status` of `running`,
`completed`, or `failed`, start and finish timestamps, a config fingerprint,
and a JSONB `stats` blob. `harvest_state` keeps the last status per
(source, entity type, filter set, institution).

Three read paths exist:

- **Public:** `GET /api/v1/meta/freshness`
  (`backend/src/journal_browser/routers/meta.py`) reports per-institution
  harvest state plus a `degraded` array fed by the
  `backend/src/journal_browser/services/source_health.py` registry, where
  serving-time code records degraded sources with a detail string and
  timestamp.
- **Admin API:** `GET /api/v1/admin/runs` (`routers/admin/runs.py`) lists
  recent runs newest first, filterable by institution, and
  `GET /api/v1/admin/flagged` lists deals needing curation.
- **Admin UI:** the harvest-runs table at the top of
  `frontend/app/admin/page.tsx` (component in
  `frontend/components/admin/runs-table.tsx`), backed by those endpoints.
  See [Admin panel](features/admin.md).

A `running` row with no finish timestamp means a job died hard, since every
normal path marks completion or failure.

## Where logs go

- **`docker compose logs`** is the primary log surface. Bootstrap prints
  one line per step (`bootstrap[step]: <command>`, then `done in Ns` or
  `FAILED (exit N)`) and a final summary naming failed steps
  (`backend/jobs/bootstrap.py`); a failure also stops new steps from
  starting. Jobs log through Python logging to stdout/stderr, which the
  containers capture.
- **`backend/landing/`** is the persistent landing zone (bind-mounted into
  the containers): raw downloaded source artifacts per source directory
  plus `landing/reports/curation_report.html` from the reconcile job. The
  `raw_files` and `source_records` tables index what landed, with hashes
  and paths. Rebuilds do not lose it.
- **`backend/logs/`** is not written by the application. It collects output
  from manually run sweeps on the host (shell redirections such as
  `cerif_sweep.log`, `enrich_full.log`); treat it as ad-hoc archaeology,
  not an app log directory.

## What does not exist

Said plainly, so nobody searches for it:

- No metrics endpoint and no Prometheus/Grafana stack.
- No distributed tracing or OpenTelemetry.
- No alerting, paging, or uptime monitoring.
- No log aggregation, rotation policy, or retention tooling.
- No scheduled harvests. Runs happen on fresh boot (auto mode), on manual
  `docker compose run` invocations of `backend/jobs/bootstrap.py`, or via
  repair flags (`--always`, `--from STEP`). Regular update harvests are a
  planned decision, not a deployed feature.

Until any of that changes, reliability rests on the compose health checks
telling you the stack is up, and `harvest_runs` telling you the data is
current. The pipeline itself is documented in
[Data pipeline](systems/data-pipeline/index.md); deployment levers live in
[Backend configuration](apps/backend/configuration.md).
