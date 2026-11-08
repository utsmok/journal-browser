# AGENTS.md — Open Journal Browser

Agent-facing guide. Human-facing docs: README.md (quick start) and
DEPLOYMENT.md (configuration reference, harvest internals, operations).

## Layout

- `backend/` — FastAPI + SQLAlchemy 2 (async), Python 3.12, managed with
  `uv`. Source: `src/journal_browser`; harvest jobs: `jobs/`; tests:
  `tests/`; offline schema dump: `scripts/dump_openapi.py`.
- `frontend/` — Next.js (App Router) + TypeScript, managed with npm.
  `lib/api-types.ts` is generated from `openapi.json` — never hand-edit.
- `openapi.json` — committed API schema (repo root); CI verifies it has not
  drifted from the routes.
- `docs/` — mostly a gitignored content volume (two files are tracked).
  `docs/data-pipeline/OVERVIEW.md` documents the harvest architecture;
  `docs/multi-institute.md` covers the shared-core multi-institution design.
- `plans/` — local-only (untracked) implementation plans; absent on fresh
  clones.

## Commands

All commands run from the repo root unless noted.

| Purpose | Command |
|---|---|
| Backend deps | `cd backend && uv sync` |
| Backend tests | `cd backend && uv run pytest -q` |
| Skip DB tests | `cd backend && JB_SKIP_DB_TESTS=1 uv run pytest -q` |
| Backend lint | `cd backend && uv run ruff check src tests jobs scripts` |
| Backend format | `cd backend && uv run ruff format src tests jobs scripts` |
| Backend types | `cd backend && uv run ty check src jobs tests scripts --exit-zero-on-warning` |
| Frontend deps | `cd frontend && npm install` |
| Frontend lint (ESLint) | `cd frontend && npm run lint` |
| Frontend format (Biome) | `cd frontend && npm run format` |
| Frontend format check (CI) | `cd frontend && npm run format:check` |
| Frontend build | `cd frontend && npm run build` |
| Refresh API types | `cd backend && uv run python scripts/dump_openapi.py && cd ../frontend && npm run generate` |
| Setup git hooks | `pre-commit install` (ruff + format + eslint/biome + file-length gate on staged files) |

## Test setup

- Tests need Postgres at `localhost:5433` (user `journal`, password
  `journal`): `docker compose up -d db`. `tests/conftest.py` creates a
  unique throwaway database per process; `JB_SKIP_DB_TESTS=1` skips DB
  tests explicitly.
- `pytest -m "not live"` is the CI default; `-m live` hits real network
  APIs and must be run deliberately.
- CI (`.github/workflows/ci.yml`) runs: ruff check + format, ty, alembic
  upgrade, pytest, the openapi drift check, eslint, biome format:check, the
  vitest suite (`npm run test`), and `next build`. The `deps-hygiene` job
  (deptry + depcheck) reports unused or unlisted dependencies and is
  advisory: it never blocks a merge.
- Logging: `logging_setup.configure_logging()` runs at app start; every
  request gets an `X-Request-ID` (honored inbound, echoed out) that lands
  on every log line, and credential-looking substrings are redacted.
  `JB_LOG_FORMAT=json` switches to one-JSON-per-line output.

## API type pipeline

After ANY backend API change: run the dump script to refresh
`openapi.json`, run `npm run generate` to refresh `lib/api-types.ts`, and
commit both together with the backend change. CI regenerates the schema and
fails if the committed file drifted.

## Conventions

- Commits: conventional commits with scope — `fix(backend): ...`,
  `feat(frontend): ...`, `test(backend): ...`, `chore(deploy): ...`.
- Backend lint: ruff, line length 100, rules E,W,F,I,UP,B,SIM,C4,RET,RUF.
  En dashes/arrows are intentional typography (allowed-confusables).
  `alembic/versions/` is never reformatted — migrations are historical
  record.
- Backend types: ty (alpha). Framework-idiom false positives are demoted to
  warnings in `[tool.ty.rules]` (backend/pyproject.toml); structural rules
  (unresolved-import, call-non-callable, invalid-raise, ...) stay at error.
  Fix real findings in code rather than widening the demotions, and promote
  rules as ty matures.
- Frontend: Biome formats (2-space, double quotes, semicolons), ESLint
  lints (`next/core-web-vitals`). One formatter, one linter — no more.
- SQLAlchemy: `CheckConstraint` + plain Text columns, not pg enums.
  Migrations must be reversible on a test DB (`alembic downgrade`).
- Feature flags: `JB_ENABLE_*` env vars flow through `settings_schema.py`
  and the admin's `settings.yaml` overlay; scaffolds stay OFF until the
  integration ships.
- Harvest jobs are idempotent and fail by naming their step. Shared query/
  facet/cache logic lives in `backend/src/journal_browser/services/` — do
  not copy it between routers (see plans 005/006).
- Deliberately rejected ideas (do not re-audit): zod at the API boundary,
  Redis caching, pg enums, JSONB→relational migration, feature-first
  directory reorganization — see "Findings considered and rejected" in
  plans/README.md.

## Working rules

- `uv` in `backend/`, `npm` in `frontend/`; never bare `python`/`pip`.
- Read before edit; keep the suite green; run the verify commands before
  reporting done.
- When executing a plan from `plans/`: read the plan fully first, honor its
  STOP conditions, run every verify line, and update the status row in
  `plans/README.md` when done.
- The live deployment runs on the media VM `192.168.2.153` (Proxmox LXC 101
  "media") since 2026-11-06: frontend published on **3001**, backend on
  `127.0.0.1:8001`, db on `127.0.0.1:5434` (see `compose.override.yml`
  there — 3000/8000 are taken by linkwarden/portainer on that host). Never
  restart, redeploy, or write to it. The live `journalbrowser` database is
  read-only for agents — SELECT ok, never DDL. From the workstation, reach
  the VM over tailscale: `ssh dockeruser@100.120.223.117` (node `media`,
  joined 2026-11-06); fallback via servtop jump
  `ssh -J sam@100.114.158.13 dockeruser@192.168.2.153` (direct LAN doesn't
  work from WSL). Public ingress
  is Caddy on the Proxmox host `192.168.2.122` (`/home/root/Caddyfile`),
  reverse-proxying `journalbrowser.samuelmok.cc` to `192.168.2.153:3001`.
  The workstation copy of the stack is stopped; local containers are not
  the live deployment.
- Tests use their own throwaway databases; test stacks go on free ports
  (`compose.test.yml`: db 5533, backend 8001).
- `JB_SKIP_EMBEDDING_WARMUP=1` skips the ~130 MB ONNX model preload on app
  import (offline schema dumps, CI). Leave unset in deployments.
