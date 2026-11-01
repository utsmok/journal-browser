# Tooling

The tools that build, check, and gate the repo, and where each is configured. The verify commands that run them are in [the contribute index](index.md).

## Backend: uv, ruff, ty

Dependencies are managed with `uv` (`cd backend && uv sync`); the dev group in `backend/pyproject.toml` carries pytest, pytest-asyncio, ruff, and ty.

Ruff is the linter and formatter, configured in `backend/pyproject.toml`: line length 100, rules `E,W,F,I,UP,B,SIM,C4,RET,RUF`, `src` set to `src`, `tests`, `jobs`, `scripts`. En dashes, arrows, and multiplication signs in strings are intentional typography, so they are listed in `allowed-confusables`. `backend/alembic/versions/` is excluded from formatting because migrations are historical record. One per-file ignore: `B008` in `backend/src/journal_browser/main.py` for FastAPI's idiomatic `Depends()` defaults.

`ty` is the type checker, and it is alpha. Several rules that misfire on SQLAlchemy, FastAPI, and pydantic idioms are demoted to warnings in `[tool.ty.rules]`; structural rules such as `unresolved-import` and `call-non-callable` stay at errors. The policy is to fix real findings in code rather than widen the demotions, and to promote rules as ty matures. CI runs it with `--exit-zero-on-warning`.

## Frontend: npm, Biome, ESLint, openapi-typescript

`frontend/package.json` defines the scripts. Biome formats (`npm run format`, checked by `npm run format:check`): 2-space indent, double quotes, semicolons. ESLint lints (`npm run lint`, `next/core-web-vitals`). One formatter and one linter, no more. `npm run generate` runs openapi-typescript over `openapi.json` to produce `frontend/lib/api-types.ts`, which is never hand-edited.

## Scripts worth knowing

- `backend/scripts/dump_openapi.py`: writes `openapi.json` at the repo root from the route and response models. It runs offline (no server or database) and sets `JB_SKIP_EMBEDDING_WARMUP=1` itself to skip the embedding-model preload.
- `backend/scripts/validate_weak_rung.sh`: an operational, fail-fast validation script for the weak-affiliation author rung. It snapshots author and identity counts against a preview database, runs `backend/jobs/resolve_author_ids.py --institution ut --no-sweeps`, prints its evidence per step, and then repeats against the live database. Because later steps write to the live DB, it is an owner-run script, not a CI tool.
- `dev/embed_title_hitrate.py`: a quality experiment for semantic search. It samples 10,000 works, embeds their titles with the BGE model, ranks journals by cosine distance over the same candidate set the semantic search uses, and reports top-1 and top-10 hit rates. Run it with `cd backend && uv run python ../dev/embed_title_hitrate.py`; it only reads the local database.

## Dependabot

`.github/dependabot.yml` keeps three ecosystems current: `uv` packages in `/backend` and npm packages in `/frontend` weekly, and GitHub Actions monthly.

## CI workflow structure

`.github/workflows/ci.yml` triggers on pushes to `main` and on pull requests, with two jobs:

- `backend`: a `pgvector/pgvector:pg17` service container on port 5433 (alembic migrations from 0020 on need `CREATE EXTENSION vector`), then `uv sync`, `ruff check`, `ruff format --check`, `ty check`, `alembic upgrade head`, `pytest -m "not live"`, and finally the OpenAPI drift check: rerun `backend/scripts/dump_openapi.py` and `git diff --exit-code -- openapi.json`.
- `frontend`: Node 22 with npm caching, then `npm ci`, `npm run lint`, `npm run format:check`, and `npm run build`.

The drift check is what makes the committed-schema convention enforceable: forgetting the type pipeline from [development workflow](development-workflow.md) fails CI, not just code review. The pytest step depends on the harness described in [testing](testing.md), and the rule style conventions are in [patterns and conventions](patterns-and-conventions.md).
