# Getting started

Two ways to run the project: the full docker-compose stack (deployment mode,
includes the harvest pipeline) or per-app development processes with a local
Postgres. The live compose project named `journal-browser` on this machine
is a production deployment; never restart or write to it. Development uses
the test stack in `compose.test.yml` (db on 5533, backend on 8001) or a
plain `docker compose up -d db` for tests.

## Prerequisites

- Docker with Compose v2.24+ (for the stack and the test database)
- `uv` (backend) and Node 22+ with `npm` (frontend) for development

## Run the full stack

1. `cp .env.example .env` and set the institution levers. At minimum:
   `JB_INSTITUTION_NAME`, `JB_INSTITUTION_ROR`, `JB_PURE_OAI_BASE_URL`,
   `JB_OPENAIRE_ORG_ID`, and `OPENALEX_API_KEY`. Every variable is
   documented in `.env.example`.
2. `docker compose up -d --build`
3. `docker compose logs -f bootstrap` — the first boot takes 1.5 to 2
   hours. The backend stays down until every harvest step succeeds.
4. Verify: `curl localhost:8000/api/v1/healthz`, then open
   `http://localhost:3000`. With one institution configured, `/` redirects
   to its site (`/ut`).

Re-running `docker compose up` re-runs `bootstrap` in `auto` mode, which
exits in seconds once journals exist. Repair paths:
`--from <step>` reruns from a named step, `--institution <code>` reruns one
university's layer. See `DEPLOYMENT.md` for the full configuration
reference.

## Backend development

```bash
cd backend && uv sync          # install deps
docker compose up -d db        # Postgres on localhost:5433 (tests need it)

uv run pytest -q               # full suite (DB-backed)
JB_SKIP_DB_TESTS=1 uv run pytest -q   # skip DB tests
uv run pytest -m live          # real network APIs; run deliberately

uv run ruff check src tests jobs scripts
uv run ruff format src tests jobs scripts
uv run ty check src jobs tests scripts --exit-zero-on-warning
```

`backend/tests/conftest.py` creates a unique throwaway database per process,
so tests never touch the dev or live database. CI runs the same commands
plus `alembic upgrade head` (migrations must apply and downgrade cleanly on
a test database).

## Frontend development

```bash
cd frontend && npm install

npm run dev          # dev server
npm run build        # production build
npm run lint         # ESLint
npm run format       # Biome format (write)
npm run format:check # Biome format (CI check)
```

`frontend/lib/api-types.ts` is generated from `openapi.json`. Never
hand-edit it.

## API type pipeline

After any backend API change, regenerate both artifacts and commit them with
the backend change:

```bash
cd backend && uv run python scripts/dump_openapi.py
cd ../frontend && npm run generate
```

CI regenerates the schema and fails if the committed `openapi.json` drifted
from the routes.

## Before you report done

Run the verify commands for what you touched: backend lint, format check,
types, and tests; frontend lint, format check, and build; and the type
pipeline after API changes. The full list lives in `AGENTS.md`.
