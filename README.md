# Journal Browser (rebuild)

A public search tool that helps researchers at the University of Twente find where to
publish: which journals are covered by open access deals, what publishing there costs,
how Twente publishes in them, and what they are about. Replaces the WUR-hosted
[Open Access Journal Browser](https://library.wur.nl/WebQuery/utbrowser) using ONLY openly 
available data. Built as a proof of concept for Twente first, maybe i'll tinker with it
so it's easy for other universities to run. The basic stack should transfer over, but
it'll need a lot of hand-tuning at this stage to deploy for other institutes. 


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

Currently selected data window: publication years 2020 to now. OpenAlex cursor-paged harvests use the
`OPENALEX_API_KEY` environment variable; single-entity lookups don't need the API key.

## Layout

```
backend/            FastAPI API (src/journal_browser) + jobs/ (ingestion) + tests/
frontend/           Next.js app (app router)
docker-compose.yml  db + backend + frontend
```

## Development

Prerequisites: `uv`, Node 22+, Docker (for Postgres), or just use compose.

```bash
# everything via docker
docker compose up --build
# frontend http://localhost:3000, API http://localhost:8000/api/v1/healthz

# backend only
docker compose up -d db
cd backend && uv sync && uv run alembic upgrade head
uv run uvicorn journal_browser.main:create_app --factory --reload

# frontend only
cd frontend && npm install && npm run dev
```

Copy `.env.example` to `.env` and set the API keys before running harvest
jobs.

## Data pipeline (run order)

```bash
cd backend
uv run python jobs/harvest_journals.py       # OpenAlex sources sweep (lands raw payloads)
uv run python jobs/backfill_issn_l.py        # deal_journals.issn_l via issn_map
uv run python jobs/ingest_openapc.py         # OpenAPC aggregates + Twente evidence
uv run python jobs/ingest_scimagojr.py       # yearly exports from landing/scimagojr/
uv run python jobs/harvest_pure.py           # Pure OAI -> canonical UT works
uv run python jobs/enrich_works.py           # OpenAlex/Crossref enrichment by DOI
uv run python jobs/harvest_stats.py          # Twente works 2020+ -> per-journal stats
uv run python jobs/backfill_flags.py         # recompute works_2020_plus / last_active_year
```

**Deals are manually added.** New or changed deals should go in through a curation
job like `jobs/apply_curation_2026_10_22.py`. This is because it's apparently 
extremely hard for publishers to just give a list of journals that are covered
in a publishing deal. (yet another reason to get ri.. uh, i mean move to diamond OA)


## License

Apache-2.0 — see [LICENSE](LICENSE).
