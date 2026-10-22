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
uv run python jobs/scrape_openaccess_nl.py   # openaccess.nl deals (raw HTML landed)
uv run python jobs/ingest_jct.py             # cOAlition S JCT dump -> deals + journals
uv run python jobs/ingest_openapc.py         # OpenAPC aggregates + Twente evidence
uv run python jobs/reconcile.py              # merge deals; curation report (HTML)
uv run python jobs/harvest_journals.py       # OpenAlex sources sweep + quality-bar counts
uv run python jobs/backfill_issn_l.py        # deal_journals.issn_l via issn_map
uv run python jobs/ingest_scimagojr.py       # yearly exports from landing/scimagojr/
uv run python jobs/backfill_flags.py         # recompute activity flags
uv run python jobs/harvest_stats.py          # Twente works 2020+ -> per-journal stats
```

`landing/reports/curation_report.html` lists every row a human should review:
unmatched deals, consortium merges without enumerated members, and unresolvable
deal-journal ISSNs. Curated fixes go through `manual_overrides` and are never
overwritten by re-ingestion.

The search API defaults to the corpus quality bar (decision 12 in
[docs/decisions.md](docs/decisions.md)); pass `scope=all` for the full corpus.
Green-OA (Jisc) and cited-by-Twente harvests are scaffolded behind config flags and
stay off until keys/approval land.

## Status

Phases 0-6 of [docs/plan.md](docs/plan.md) are built and verified against live
sources: deal ingestion (JCT + openaccess.nl + OpenAPC + reconcile), the OpenAlex
sources sweep (177k journals), scimagojr metrics, Twente statistics, the search API,
and the frontend with the limitations/caveat system. Phase 7 (compose smoke test +
parity checklist) is the remaining v1 item; phases 8-10 (Pure/OpenAIRE/Crossref) are
specified in [docs/plan-pure-openaire-crossref.md](docs/plan-pure-openaire-crossref.md).
