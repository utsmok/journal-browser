# Journal Browser (rebuild)

A public search tool that helps researchers at the University of Twente find where to
publish: which journals are covered by open access deals, what publishing there costs,
how Twente publishes in them, and what they are about. Replaces the WUR-hosted
[Open Access Journal Browser](https://library.wur.nl/WebQuery/utbrowser) with OpenAlex
as the single bibliometric data source. Built as a proof of concept for Twente first,
then released as an open-source project other universities can run.

- **Scope & background**: [docs/scope.md](docs/scope.md)
- **Implementation plan**: [docs/plan.md](docs/plan.md)
- **Research**: [docs/research/](docs/research/) — current browser, openaccess.nl, deal
  data sources (JCT/ESAC), OpenAlex, OpenAPC/Jisc, prior art, aletheca/ut-metadata
- **Decisions & open questions**: [docs/decisions.md](docs/decisions.md)

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

Data window: publication years 2020 to now. OpenAlex cursor-paged harvests use the
`OPENALEX_API_KEY` environment variable; single-entity lookups stay keyless.

## Layout

```
backend/            FastAPI API (src/journal_browser) + jobs/ (ingestion) + tests/
frontend/           Next.js app (app router)
docs/               scope, plan, decisions, research/
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

Copy `.env.example` to `.env` and set `JB_OPENALEX_API_KEY` before running harvest
jobs (only cursor-paged harvests use the key; single-entity lookups are keyless).

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

**Deals are manual.** The deal register is exactly the owner-verified deals carrying a
`deal_institutions` link to the home institution (16 as of 2026-10-23). Nothing
auto-writes deals: the JCT/openaccess.nl/reconcile harvesters were removed on
2026-10-23 (owner decision; see decisions.md #14), and `jobs/purge_non_twente_deals.py`
deletes any deal without a home link. New or changed deals go in through a curation
job like `jobs/apply_curation_2026_10_22.py`; raw JCT/openaccess.nl copies stay in
`landing/` for reference.

The search corpus is everything with more than 3 publications since 2020
(`works_2020_plus > 3`, owner decision; see decisions.md #15). Green-OA (Jisc) and
cited-by-Twente harvests are scaffolded behind config flags and stay off until
keys/approval land.

## Status

Phases 0-10 of [docs/plan.md](docs/plan.md) are built: the OpenAlex sources sweep,
scimagojr metrics, Pure-canonical Twente statistics (Pure OAI + OpenAIRE/Crossref
enrichment), the search API, and the frontend with the limitations/caveat system.
Deal data is a manually maintained register (decisions.md #14); the corpus presents
journals with >3 works since 2020 (decisions.md #15). Post-review fixes and the
owner-decision changes are described in [docs/review-2026-10-22.md](docs/review-2026-10-22.md).
