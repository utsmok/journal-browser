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
cd backend && uv sync && uv run uvicorn journal_browser.main:app --reload

# frontend only
cd frontend && npm install && npm run dev
```

Copy `.env.example` to `.env` and set `OPENALEX_API_KEY` before running harvest jobs.

## Status

Skeleton + research/plan phase. Phases 1-6 (deal ingestion, journal harvest, statistics,
search API, frontend, caveat system) are specified in [docs/plan.md](docs/plan.md).
