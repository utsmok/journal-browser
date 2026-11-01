# How to contribute

Journal Browser is a solo-maintained project, so the contribution rules live in one place and stay short. This page is the entry point; the pages under `how-to-contribute/` expand each topic.

## Read AGENTS.md first

`AGENTS.md` at the repo root is the normative working guide. It defines the toolchain split (`uv` in `backend/`, `npm` in `frontend/`), the verify commands, test setup, commit style, and the live-deployment safety rules. When this wiki and `AGENTS.md` disagree, `AGENTS.md` wins. The other normative documents are `README.md` (quick start) and `DEPLOYMENT.md` (configuration reference, harvest internals, operations).

## Verify commands

Run these before reporting any change as done:

| Purpose | Command |
|---|---|
| Backend tests | `cd backend && uv run pytest -q` |
| Skip DB tests | `cd backend && JB_SKIP_DB_TESTS=1 uv run pytest -q` |
| Backend lint | `cd backend && uv run ruff check src tests jobs scripts` |
| Backend format | `cd backend && uv run ruff format src tests jobs scripts` |
| Backend types | `cd backend && uv run ty check src jobs tests scripts --exit-zero-on-warning` |
| Frontend lint | `cd frontend && npm run lint` |
| Frontend format check | `cd frontend && npm run format:check` |
| Frontend build | `cd frontend && npm run build` |

After any backend API change, also refresh the committed schema: `cd backend && uv run python scripts/dump_openapi.py && cd ../frontend && npm run generate`, and commit both outputs with the backend change. See [development workflow](development-workflow.md) and [tooling](tooling.md).

## What CI enforces

`.github/workflows/ci.yml` runs two jobs on every push to `main` and every pull request:

- Backend: `ruff check` and `ruff format --check`, `ty`, `alembic upgrade head`, `pytest -m "not live"` against a pgvector Postgres service, then an OpenAPI drift check (regenerate `openapi.json` and fail if the committed file differs).
- Frontend: `npm run lint` (ESLint), `npm run format:check` (Biome), and `npm run build` (which typechecks).

Details on each gate are in [tooling](tooling.md); the test setup behind the pytest step is in [testing](testing.md).

## Where to go next

- [Development workflow](development-workflow.md): the branch, commit, and PR cycle, plus the live-deployment safety rules.
- [Testing](testing.md): the throwaway-database test harness and the suite layout.
- [Debugging](debugging.md): a troubleshooting runbook for pipeline and API failures.
- [Tooling](tooling.md): ruff, ty, Biome, ESLint, scripts, Dependabot, and CI structure.
- [Patterns and conventions](patterns-and-conventions.md): the recurring code patterns and the deliberately rejected ideas.
- [Getting started](../overview/getting-started.md): running the stack locally for the first time.
