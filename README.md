# Journal Browser (rebuild)

A public search tool that helps researchers at the University of Twente find where to
publish: which journals are covered by open access deals, what publishing there costs,
how Twente publishes in them, and what they are about. Replaces the WUR-hosted
[Open Access Journal Browser](https://library.wur.nl/WebQuery/utbrowser) using ONLY openly
available data. Any Dutch institute can run its own instance: set the institution
ROR, repository OAI-PMH endpoint, and an OpenAlex key in `.env`, then
`docker compose up` — the one-shot `bootstrap` service fills the database

## First-time install

1. Install Docker (Compose v2.6+; `!override` in the test overrides needs
   Compose v2.24+).
2. `cp .env.example .env`, then set the institution levers:

   | Variable | What it is | How to find it |
   |---|---|---|
   | `JB_INSTITUTION_NAME` | Your institution's English name as deal pages write it | openaccess.nl deal pages |
   | `JB_INSTITUTION_ROR` | Your ROR id | <https://ror.org> search |
   | `JB_PURE_OAI_BASE_URL` | Your repository's anonymous OAI-PMH endpoint | Pure: `https://<portal>/ws/oai?verb=Identify` must answer |
   | `JB_OPENAIRE_ORG_ID` | OpenAIRE organization id (unset = OpenAIRE harvest off) | `api.openaire.eu/graph/v1/organizations?legalName=<name>` |
   | `OPENALEX_API_KEY` | Free OpenAlex key for cursor-paged harvests | <https://openalex.org> users page |
   | `JB_DATA_WINDOW_START`/`_END` | Publication-year window (default 2020..now) | your choice |

3. `docker compose up -d --build`.
4. Watch the first boot: `docker compose logs -f bootstrap` (30–60 min,
   fully automatic; the backend stays down until every step succeeds).
5. Verify: `curl localhost:8000/api/v1/healthz`, then open
   `http://localhost:3000` — the deal register should list your
   institution's current NL deals with journal counts.

Optional: `JB_UT_METADATA_DSN` (Twente's ut-metadata Postgres) is Twente-only;
leave it empty elsewhere. `JB_CONTACT_EMAIL` identifies you to OpenAlex's
polite pool.

Reference second-institute deployment: `compose.groningen.yml`
(University of Groningen, ports 5543/8002/3002) — run with
`docker compose -p <name> -f docker-compose.yml -f compose.groningen.yml up -d --build`.


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
`needs_curation`. The one remaining manual helper covers a gap the public
sources cannot fill: `jobs/ingest_emerald_contract.py` (OCR'd contract
journal list, needed only while the JCT dump serves Emerald the wrong
sheet).

Deals that only exist on openaccess.nl (no JCT sheet — ACM, ACS,
Amsterdam University Press, IOS Press) are derived automatically:
participation is parsed from the deal page's conditions text (an
enumerated institution list, or "all Dutch universities" when none is
enumerated), and coverage is the publisher's journal corpus
(`deal_journals.source = 'publisher-pattern'`). Pages whose list omits
your institution leave the deal unlinked, and the purge drops it.


## License

Apache-2.0 — see [LICENSE](LICENSE).
