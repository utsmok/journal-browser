# Testing

Backend tests are DB-backed and mandatory; the frontend has no unit test suite. This page explains both, plus the migration contract CI enforces.

## The backend test harness

Everything lives in `backend/tests/conftest.py`. Read it before writing your first test; its rules are:

- Tests need Postgres at `localhost:5433` (user `journal`, password `journal`), normally `docker compose up -d db`. If the database is unreachable, the run fails loudly at startup.
- `JB_SKIP_DB_TESTS=1` (`cd backend && JB_SKIP_DB_TESTS=1 uv run pytest -q`) skips database tests as an explicit opt-out. There is no silent skip path.
- Each pytest process creates one throwaway database named `journalbrowser_pytest_<pid>_<hex>`, so two concurrent runs never fight. Set `JB_TEST_DB` to override the name. Administrative `CREATE`/`DROP` statements go through the always-present `postgres` maintenance database, not `journalbrowser`.
- The `db_engine` fixture is function-scoped: it drops and recreates the throwaway database per test, enables the `pgvector` extension before `create_all` (the `journals.embedding` column needs it), and clears the facet and snapshot caches so no state leaks between tests.
- The `client` fixture overrides the `get_session` dependency, so API tests run through the real ASGI app against the throwaway database. Helpers include `institution_factory` (hosted institution rows) and `journal_factory` (journal rows with sane defaults).

## The live marker

`backend/pyproject.toml` defines a `live` pytest marker for tests that hit real network APIs. `pytest -m "not live"` is the CI default and what you run normally; `pytest -m live` is a deliberate act for checking actual source behavior. Keep anything network-dependent behind that marker.

## The suite at a glance

`backend/tests/` holds 46 test files plus `conftest.py`. The notable suites:

- `backend/tests/test_search_scopes.py`: the largest suite, covering FTS scopes and filtering across institutions.
- `backend/tests/test_publishers.py`: publisher lineage and the publisher snapshot serving.
- `backend/tests/test_author_ids.py` and `backend/tests/test_author_cascade.py`: the author identity cascade (orcid-exact through fuzzy rungs); `backend/tests/test_authors_ingest.py`, `backend/tests/test_authors_api.py`, and `backend/tests/test_local_author_adapter.py` cover the roster ingest and its API.
- `backend/tests/test_pure_portal.py` and `backend/tests/test_pure_portal_persons.py`: the Pure portal adapter, including the persons walk.
- `backend/tests/test_reconcile.py`: deal/works reconciliation.
- `backend/tests/test_admin.py` and `backend/tests/test_admin_deals.py`: the admin API, deals curation.
- Small guard suites worth knowing: `backend/tests/test_route_precedence.py` (admin/feedback/docs routers register before the `/{institution_code}` catch-all), `backend/tests/test_state_constraints.py` and `backend/tests/test_schema_contract.py` (CheckConstraint and schema invariants), `backend/tests/test_multi_institution.py`, and `backend/tests/test_audit_regressions.py` (regressions found by audits).

## The migration contract

Migrations must be reversible on a test database: `alembic upgrade head` followed by `alembic downgrade` has to work, and CI runs the upgrade as a gate. `backend/alembic/versions/` is never reformatted because migrations are historical record. Models follow the schema conventions described in [the data model page](../systems/data-model.md).

## The frontend has no unit tests

There is no frontend unit or component test suite. Say so plainly in reviews and do not assume one exists. What protects the frontend instead:

- TypeScript checks run inside `npm run build` (a CI gate), so type breaks fail the build.
- Generated API types in `frontend/lib/api-types.ts` keep the frontend honest against the committed `openapi.json`; the backend CI job fails if that file drifts. See [development workflow](development-workflow.md) for the regeneration commands.
- ESLint (`npm run lint`) and Biome (`npm run format:check`) are also CI gates.

If you add a frontend feature with subtle logic, consider whether a backend test can pin the contract instead; the API level is where this project concentrates its assertions. When a change breaks the stack, [debugging](debugging.md) is the runbook to reach for.
