# Journal Browser (rebuild)

A public search tool that helps researchers find where to publish: which
journals are covered by open access deals, what publishing there costs, how
their institution publishes in them, and what the journals are about. Replaces
the WUR-hosted [Open Access Journal
Browser](https://library.wur.nl/WebQuery/utbrowser) using only openly
available data.

Any Dutch (or international) institute can run its own instance: set the
institution variables in `.env`, `docker compose up`, and the one-shot
`bootstrap` service fills the database — journals, the NL deal register,
your repository's works, APC evidence, quartiles, and statistics. Every UI
label follows the configured institution.

## Quick start

1. Install Docker (Compose v2.24+).
2. `cp .env.example .env` and set the institution levers — at minimum:
   `JB_INSTITUTION_NAME`, `JB_INSTITUTION_ROR`, `JB_PURE_OAI_BASE_URL`,
   `JB_OPENAIRE_ORG_ID`, and `OPENALEX_API_KEY`.
3. `docker compose up -d --build`.
4. `docker compose logs -f bootstrap` — the first boot takes 1.5–2 hours
   (fully automatic; the backend stays down until every step succeeds).
5. Verify: `curl localhost:8000/api/v1/healthz`, then open
   `http://localhost:3000` — the deal register should list your
   institution's current NL deals with journal counts.

The full guide — configuration reference, harvest internals, admin panel,
second-institute deployment, maintenance — is in
[DEPLOYMENT.md](DEPLOYMENT.md). A tested second-institute reference stack
lives in `compose.groningen.yml` (University of Groningen).

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 (async), `uv` |
| Database | PostgreSQL 17 |
| OpenAlex | [`aletheca`](https://github.com/utsmok/aletheca) (bibliofabric-based client) |
| OpenAIRE | [`aireloom`](https://github.com/utsmok/AIREloom) |
| Crossref | [`stavrophora`](https://github.com/utsmok/stavrophora) |
| Frontend | Next.js (App Router), TypeScript |
| Deployment | Docker Compose (LAN server for the PoC) |

OpenAlex cursor-paged harvests use `OPENALEX_API_KEY`; single-entity lookups
don't need it.

## Layout

```
backend/    FastAPI app, harvest jobs, alembic migrations
frontend/   Next.js app (App Router)
data/       Scimago seed CSVs (backend/data/scimagojr)
landing/    Raw harvest files (gitignored) + curation reports
```

## Development

Prerequisites: `uv`, Node 22+, Docker (for Postgres), or just use compose.

```bash
# backend tests: need the compose Postgres on localhost:5433
# (docker compose up -d db), or set JB_SKIP_DB_TESTS=1
cd backend && uv run pytest

# frontend
cd frontend && npm install && npm run build
```

The bootstrap pipeline (`backend/jobs/bootstrap.py`) runs the harvest jobs as
a dependency DAG — independent sources run concurrently, dependents start as
soon as their inputs are in, and `--from <step>` is the serial repair path.
Every job is idempotent; a failure names the step. See
[DEPLOYMENT.md](DEPLOYMENT.md) for what each job builds and how the deal
register is reconciled.

## License

Apache-2.0 — see [LICENSE](LICENSE).
