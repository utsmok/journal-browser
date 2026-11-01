# Patterns and conventions

The rules that keep the codebase consistent. `AGENTS.md` is the normative
version; this page explains the patterns you will meet in the code and why
they exist.

## Backend

**Data layer.** Models use `CheckConstraint` + plain `Text` columns instead
of pg enums (see `backend/src/journal_browser/models/`). Enums in Postgres
are painful to alter; a check constraint plus a text column migrates with a
simple DDL swap. Migrations in `backend/alembic/versions/` must downgrade
cleanly on a test database, and are never reformatted — they are historical
record, which is why ruff excludes that directory.

**Layering.** HTTP lives in `backend/src/journal_browser/routers/`, shared
query/facet/cache logic in `backend/src/journal_browser/services/`, tables in
`models/`. The rule from `AGENTS.md`: do not copy shared logic between
routers; move it into `services/`. Facets, caching, and query building are
the classic offenders.

**Route precedence.** Global routers (`admin`, `feedback`, `docs`) mount
before the `/{institution_code}` scoped router in
`backend/src/journal_browser/main.py`, so `/admin/deals` is not captured as
institution `admin`. `backend/tests/test_route_precedence.py` pins this.

**Errors and pagination.** Handlers raise `ValueError` for malformed input
(cursor decoding in `services/`); the app factory maps `ValueError` to a
400 response. FastAPI's own validation produces 422s at the boundary. List
endpoints paginate with opaque cursors (`parse_cursor`).

**Jobs.** Every job in `backend/jobs/` is idempotent and fails by naming its
step. The DAG runner (`bootstrap.py`) supports `--from <step>`,
`--institution <code>`, and `--always` for repairs. A new harvest job
belongs in `backend/src/journal_browser/harvest/` with its CLI in
`backend/jobs/`.

**Feature flags.** `JB_ENABLE_*` flags flow through
`backend/src/journal_browser/settings_schema.py` and the admin's
`settings.yaml` overlay. Scaffolds (Jisc policies, journal citations) stay
OFF until the integration ships; `backend/tests/test_scaffolds.py` asserts
they stay dark.

**Settings.** Runtime-editable settings go through `settings_schema.py`
(one `FieldDef` per knob, global vs institution sections). Secrets are
masked in API responses. `database_url` is deliberately not editable at
runtime.

**Typography.** En dashes, arrows, and multiplication signs in strings and
docstrings are intentional; ruff's `allowed-confusables` permits them. Line
length is 100; rule set is `E,W,F,I,UP,B,SIM,C4,RET,RUF`.

**Type checking.** `ty` is alpha; SQLAlchemy/FastAPI/pydantic idiom false
positives are demoted to warnings in `backend/pyproject.toml`
(`[tool.ty.rules]`). Fix real findings in code rather than widening the
demotions.

## Frontend

**Generated types.** `frontend/lib/api-types.ts` is generated from
`openapi.json` via `npm run generate` (openapi-typescript). Never hand-edit
it; regenerate after any backend API change and commit both together. CI
fails on drift.

**One formatter, one linter.** Biome formats (2-space, double quotes,
semicolons); ESLint with `next/core-web-vitals` lints. No other tools.

**Data fetching.** React Query (`@tanstack/react-query`) wraps the typed
client in `frontend/lib/api.ts`; tables use `@tanstack/react-table`. The
institution context comes from `frontend/hooks/use-institution.tsx`, which
scopes every request to the current `/{code}`.

**Institution scoping.** All pages live under `frontend/app/[inst]/`, so
the institution code is a route param end to end. The root `/` renders the
landing chooser when multiple institutions are hosted.

## Commits and CI

- Conventional commits with scope: `fix(backend): ...`,
  `feat(frontend): ...`, `test(backend): ...`, `chore(deploy): ...`.
- CI (`.github/workflows/ci.yml`) runs ruff check + format, ty, alembic
  upgrade, pytest (`-m "not live"`), the openapi drift check, ESLint,
  Biome format check, and `next build`.
- The committed `openapi.json` must match the routes; run
  `backend/scripts/dump_openapi.py` + `npm run generate` after API changes.

## Environment rules that protect the live system

- The compose project `journal-browser` (ports 3000/8000) is a live
  deployment: never restart, redeploy, or write to it.
- The live `journalbrowser` database is read-only for agents: SELECT ok,
  never DDL. Tests use their own throwaway databases.
- Test stacks go on free ports (`compose.test.yml`: db 5533, backend 8001).
- `JB_SKIP_EMBEDDING_WARMUP=1` skips the ~130 MB ONNX model preload on app
  import (offline schema dumps, CI). Leave unset in deployments.
