# Journal Browser (rebuild)

A public search tool that helps researchers at the University of Twente find where to
publish: which journals are covered by open access deals, what publishing there costs,
how Twente publishes in them, and what they are about. Replaces the WUR-hosted
[Open Access Journal Browser](https://library.wur.nl/WebQuery/utbrowser) using ONLY openly
available data. Any Dutch institute can run its own instance: set the institution
ROR, repository OAI-PMH endpoint, and an OpenAlex key in `.env`, then
`docker compose up` — the one-shot `bootstrap` service fills the database
automatically (journals, deals, APCs, repository works, stats).


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

Copy `.env.example` to `.env` and set the institution levers (ROR + name,
OAI-PMH endpoint, OpenAlex key). On `docker compose up` the `bootstrap`
service runs `backend/jobs/bootstrap.py`: OpenAlex journals sweep →
openaccess.nl + JCT deal harvest (with the duplicate-sheet guard) → OpenAPC →
Scimago (seeded from `backend/data/`, scimagojr.com is Cloudflare-hard) →
repository OAI-PMH (`harvest_pure`) → OpenAlex/Crossref enrichment → OpenAIRE
→ per-journal stats → flags → embeddings. Every step is an idempotent job; a
failure keeps the backend down and the failing step is named in
`docker compose logs bootstrap`. Restart with `JB_BOOTSTRAP=always` (or
`jobs/bootstrap.py --always`) to re-run the whole pipeline on demand.

`JB_DATA_WINDOW_START` / `JB_DATA_WINDOW_END` bound every harvest
(default 2020..now).

Deals are auto-harvested from openaccess.nl (the canonical NL register) and
the JCT public dump; `ManualOverride` rows keep hand fixes winning over
re-harvests. When JCT links two agreements to one wrong sheet (live case:
Emerald 2025 UKB served Elsevier's list), `reconcile` assigns the sheet to
the publisher it actually matches and flags the other deal
`needs_curation`. One-off curation helpers remain for gaps the public
sources cannot fill: `jobs/apply_curation_2026_10_22.py` (frozen snapshot
register), `jobs/ingest_emerald_contract.py` (OCR'd contract journal list),
`jobs/seed_deal_links.py`.


## License

Apache-2.0 — see [LICENSE](LICENSE).
