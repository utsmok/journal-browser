# Development workflow

The cycle is: branch, change, verify locally, open a pull request. `AGENTS.md` is the normative guide; this page walks the loop.

## Toolchain split

Use `uv` for everything under `backend/` and `npm` for everything under `frontend/`. Never invoke bare `python` or `pip`; run backend code through `cd backend && uv run ...`. Install dependencies with `cd backend && uv sync` and `cd frontend && npm install` before your first run.

## Branch, commit, pull request

- Commits follow conventional commits with a scope, matching the existing history: `fix(backend): ...`, `feat(frontend): ...`, `test(backend): ...`, `chore(deploy): ...`.
- Keep the suite green and run the verify commands from [the contribute index](index.md) before reporting done.
- Open pull requests against `main`. CI runs the backend and frontend gates on every PR; see [tooling](tooling.md) for what each gate checks.

## Live deployment safety

The compose project `journal-browser` (ports 3000 and 8000) is a live deployment. Never restart, redeploy, or write to it. The live `journalbrowser` database is read-only for agents: `SELECT` is fine, DDL is not.

For tests, start only the dev database service (`docker compose up -d db`, Postgres at `localhost:5433`). For an isolated full stack, use the test overlay `compose.test.yml` instead:

```
export OPENALEX_API_KEY=...
docker compose -p jb-test -f docker-compose.yml -f compose.test.yml up -d --build
```

This simulates a fresh deployment of another institute on its own ports (db 5533, backend 8001, frontend 3001), its own landing directory (`backend/landing-test`), and its own volume, with the publication window pinned to 2025. It never touches the live stack.

## Offline runs and the embedding warmup

Importing the app preloads the BGE embedding model (~130 MB ONNX). Set `JB_SKIP_EMBEDDING_WARMUP=1` to skip that preload for offline work such as schema dumps; CI does this automatically. Leave the variable unset in real deployments. `backend/scripts/dump_openapi.py` sets it for you.

## The API type pipeline

After any backend API change, regenerate the committed schema and the frontend types, and commit them together with the backend change:

```
cd backend && uv run python scripts/dump_openapi.py
cd ../frontend && npm run generate
```

`backend/scripts/dump_openapi.py` writes `openapi.json` at the repo root; `npm run generate` regenerates `frontend/lib/api-types.ts` from it. Never hand-edit either file. CI regenerates the schema and fails if the committed copy drifted. The resulting API surface is described in [the backend app page](../apps/backend/api-surface.md).

## Working from plans

The `plans/` directory is local-only and untracked, so it is absent on fresh clones. When a plan exists and you execute it: read the plan fully before starting, honor its STOP conditions, run every verify line it lists, and update the status row in `plans/README.md` when done.

## Conventions you will hit immediately

Code patterns (CheckConstraint over pg enums, shared logic in `services/`, feature flags) are cataloged in [patterns and conventions](patterns-and-conventions.md). Idempotent harvest jobs and how failures name themselves are covered in [the data pipeline pages](../systems/data-pipeline/index.md).
