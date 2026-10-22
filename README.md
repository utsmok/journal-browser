# Journal Browser (rebuild)

A public search tool that helps researchers find where to publish: which journals are
covered by open access deals, what publishing there costs, how our university publishes
in them, and what they are about. Replaces the WUR-hosted
[Open Access Journal Browser](https://library.wur.nl/WebQuery/utbrowser) with OpenAlex as
the single bibliometric data source.

- **Scope & background**: [docs/scope.md](docs/scope.md)
- **Implementation plan**: [docs/plan.md](docs/plan.md)
- **Research**: [docs/research/](docs/research/) — current browser, openaccess.nl, deal
  data sources (JCT/ESAC), OpenAlex capabilities, prior art
- **Decisions & open questions**: [docs/decisions.md](docs/decisions.md)

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 (async), `uv` |
| Database | PostgreSQL 17 |
| Bibliometric data | OpenAlex (client built on `bibliofabric`) |
| Frontend | Next.js (App Router), TypeScript |
| Deployment | Docker Compose |

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

Copy `.env.example` to `.env` and set `JB_OPENALEX_MAILTO` / API key before running
ingestion jobs.

## Status

Skeleton + research/plan phase. Phases 1–5 (deal ingestion, journal backbone, search
API, frontend, curation) are specified in [docs/plan.md](docs/plan.md).
