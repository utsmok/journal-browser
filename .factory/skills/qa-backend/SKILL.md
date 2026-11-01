---
name: qa-backend
description: >
  QA tests for the journal-browser FastAPI backend. Functional API testing of
  search, facets, pagination, OA classification, deals, docs, feedback, and the
  admin surface against the disposable journalbrowser_qa database.
---

# Backend QA (FastAPI API)

The backend serves the public read surface anonymously and the admin surface
behind a password-derived bearer token. All QA writes land in the disposable
`journalbrowser_qa` database only.

## Testing target

Run the QA backend locally from the checked-out branch. There are no preview
deployments; never fall back to a remote or live deployment.

Boot (from repo root; requires `QA_ADMIN_PASSWORD` to be set and `uv sync`
done):

```bash
cd backend && \
  JB_DATABASE_URL=postgresql+asyncpg://journal:journal@127.0.0.1:5433/journalbrowser_qa \
  JB_SETTINGS_YAML=/tmp/qa-settings.yaml \
  JB_UT_METADATA_DSN= \
  JB_ADMIN_PASSWORD="$QA_ADMIN_PASSWORD" \
  uv run --no-dev alembic upgrade head && \
  JB_DATABASE_URL=postgresql+asyncpg://journal:journal@127.0.0.1:5433/journalbrowser_qa \
  JB_SETTINGS_YAML=/tmp/qa-settings.yaml \
  JB_UT_METADATA_DSN= \
  JB_ADMIN_PASSWORD="$QA_ADMIN_PASSWORD" \
  uv run --no-dev uvicorn journal_browser.main:app --host 127.0.0.1 --port 8100
```

Poll `GET http://127.0.0.1:8100/api/v1/healthz` until it answers. `healthz`
executes `SELECT 1`, so it also proves database connectivity.

Hard rules:

- Ports 3000 and 8000 belong to the LIVE compose deployment. Never bind them.
- `JB_SETTINGS_YAML=/tmp/qa-settings.yaml` is not optional. Without it the app
  reads and WRITES the repo's `backend/settings.yaml`, which the live
  container mounts. If a settings PUT ever wrote the repo overlay, treat the
  run as an incident: restore the file from git and report.
- Exact query parameters for each endpoint come from the committed
  `openapi.json`. Check it instead of guessing parameter names.

## Seeding the QA database

Two tiers, chosen by what exists:

1. **Full dump (local machine, preferred).** `createdb` + `pg_restore` from
   `backups/live-pre-author-path-2026-10-31.dump` (3.1 GB, custom format; use
   `pg_restore --list` to confirm). Restore takes minutes. The dump predates
   the current migrations, so run `alembic upgrade head` afterwards -- the
   upgrade path itself is a useful migration check. Postgres client binaries
   (`createdb`, `pg_restore`, `psql`) are installed locally; if a machine
   lacks them, run them via `docker exec` against the compose db container.
2. **Fixtures (CI, or when no dump is available).** After
   `alembic upgrade head`:
   `JB_DATABASE_URL=...journalbrowser_qa uv run python scripts/seed_fixtures.py`
   (from `backend/`) inserts one institution (`ut`), four journals (gold
   with APC, diamond, subscription, generic-candidate) with
   per-institution flags, and one current deal with coverage and
   participation. Idempotent.

Seeding is setup, not a test row. If the database cannot be seeded, report all
backend flows as BLOCKED with the seed error.

## Personas

- **visitor (anonymous):** everything except `/api/v1/admin/*`. Include at
  least one admin-route probe: it must return 401 (missing/invalid token
  while admin is enabled). 403 from an admin route means the admin surface
  is disabled, i.e. the boot env is wrong.
- **admin:** log in once per run via `POST /api/v1/admin/login` with the
  password from `QA_ADMIN_PASSWORD`; reuse the returned token for admin
  flows. A wrong password must fail; an empty configured password disables
  the whole admin surface (every admin route 403s) -- if that happens, the
  boot environment is wrong, report BLOCKED.

## Flow menu (pick by diff; not a checklist)

**Health and institutions**
1. `GET /api/v1/healthz` returns 200 with `{"status": "ok"}` and a version.
2. `GET /api/v1/institutions` lists `ut` with display fields (library URL,
   support email) and data-window years.

**Search and discovery** (`/api/v1/ut/...`)
3. Journal search `GET /api/v1/ut/journals?q=...`: fixture text "hydro" finds
   the two hydro journals; results carry OA classification fields. Verify
   scopes (`search_in=title|publisher|topic|all` per openapi.json) return
   plausible different results.
4. Facets: request the facets sidecar/params per openapi.json; counts must
   reflect the fixture (e.g., deal-covered facet counts the gold journal).
5. Cursor pagination: page through with the returned cursor; rows must not
   repeat and must remain stable across two consecutive fetches.
6. Semantic search `GET /api/v1/ut/journals/semantic-search?q=water
   modelling`: returns 200 with results that include the water journals.
   Do NOT assert a specific ranking: the query is embedded by the real
   bge-small model while the fixture vectors are synthetic, so ordering is
   not meaningful (cluster ranking is covered by flow 7, which compares
   fixture-to-fixture vectors). First call may pause while the ONNX model
   loads.
7. Similar journals `GET /api/v1/ut/journals/1111-1111/similar` returns the
   hydro-adjacent fixtures, not the unrelated publishing journal.
8. Journal detail `GET /api/v1/ut/journals/{issn_l}` for the gold fixture:
   shows APC evidence, quartile, deal coverage, and works endpoint linkage
   (`.../works` may be empty -- empty is fine, errors are not).

**Directories**
9. Authors `GET /api/v1/ut/authors` and publisher search/detail
   (`/api/v1/ut/publishers`, `/api/v1/ut/publishers/{name}`): 200 with
   well-shaped payloads on fixture publishers; empty author lists are valid.
10. Org units: `GET /api/v1/ut/orgunits` and one scoped variant
    (`faculty|group|institute`): 200s; empty lists valid.

**Deals, docs, meta, feedback**
11. `GET /api/v1/ut/deals` lists the fixture deal with journal counts; the
    detail endpoint returns coverage rows including the gold journal.
12. `GET /api/v1/docs` lists documents; `GET /api/v1/docs/{slug}` returns
    markdown blocks. With `JB_DOCS_DIR` unset the backend falls back to the
    repo's `docs/` directory, so a repo-booted QA backend serves at least
    the two tracked docs; an empty list is acceptable only when
    `JB_DOCS_DIR` points at an empty directory.
13. `GET /api/v1/ut/meta/limitations` and `.../meta/freshness`: 200; freshness
    may show an empty harvest history on the fixture database.
14. Visitor feedback: `POST /api/v1/feedback` with title/description/category
    returns success; the item then appears to the admin triage flow (flow 17).

**Admin surface** (admin persona, bearer token from login)
15. Auth negatives: no token on `GET /api/v1/admin/settings` -> 401; wrong
    password on login -> 403; garbage token -> 401. (403 on an admin route
    with a token present means admin is disabled -- env misconfiguration.)
16. Settings: `GET /api/v1/admin/settings` shows global fields with the four
    secrets masked (`********`); `PUT` a harmless global field (e.g.,
    `contact_email` -- NOT `library_url`, which is per-institution and
    rejected by this endpoint) and read it back; secrets must not
    round-trip in responses. Writes must land in `/tmp/qa-settings.yaml`
    (the isolated overlay), never the repo file.
17. Feedback triage: `GET /api/v1/admin/feedback` lists the flow-14 item;
    `PATCH` its status/priority; re-GET reflects the change.
18. Deals curation: `GET/PUT /api/v1/admin/deals/{id}`; flip a display field
    and read it back. `GET /api/v1/admin/flagged` runs without error.
19. Author identities: `GET/PUT /api/v1/admin/author-identities` responds
    correctly on the (likely empty) fixture data.
20. Runs: `GET /api/v1/admin/runs` returns the (possibly empty) harvest-run
    list.

**Negative and boundary (visitor)**
21. Unknown institution: `GET /api/v1/nope/journals` -> 404.
22. Malformed cursor: repeat a search with a corrupted cursor value -> 400
    (the app maps ValueError to 400; FastAPI validation errors are 422 --
    match the observed code to openapi.json semantics).
23. A trailing-slash or method-mismatch probe documents router behavior
    without asserting a specific code unless openapi.json implies one.

## Error handling and edge cases

- Fixture journal ISSNs are fake on purpose; anywhere they appear, do not
  resolve them against real ISSN registries.
- The fixture database has no `harvest_runs`, so freshness and runs flows
  exercise the empty path.
- `JB_SKIP_EMBEDDING_WARMUP` stays unset; the semantic flow pays the model
  load once.

## Known failure modes

1. **Port 8000/3000 already bound.** The live compose project owns them.
   Always boot QA on 8100 (backend) and 3100 (frontend). If 8100 is taken by
   a stale QA run, kill that process (it is QA-owned), not the live stack.
2. **Settings overlay hazard.** Booting without `JB_SETTINGS_YAML` points
   settings writes at the live-mounted `backend/settings.yaml`. If admin
   settings flows ran without the isolation var, report BLOCKED, restore the
   file with git, and flag the run.
3. **Dump schema behind code.** `live-pre-author-path-2026-10-31.dump`
   restores an older schema; `alembic upgrade head` after restore is
   required and expected to run several migrations. A failed upgrade is a
   real finding, not a seed problem.
4. **Empty database after CI service race.** If `journals` is missing, the
   migrate+seed steps failed; do not improvise schema by hand, report BLOCKED.
5. **Semantic search slow first hit.** The fastembed ONNX model (~130 MB)
   loads on first use; allow a generous timeout before calling it a failure.
6. **ValueError->400 vs 422.** App-level ValueError maps to 400; FastAPI
   boundary validation returns 422. Use openapi.json semantics when
   asserting.
7. **Journal detail hangs ~60s per view.** `ut_metadata`
   (`services/ut_metadata.py`) opens its own engine to the read-only
   ut-metadata database (live container `ut-metadata-db-1`, host port 5434)
   using the DSN from `settings.yaml`/`JB_UT_METADATA_DSN`. From a host-run
   QA backend that connection can stall until the 60s asyncpg timeout,
   then the route degrades to works_stats-only. The QA boot above sets
   `JB_UT_METADATA_DSN=` (empty) so the endpoint degrades instantly; detail
   flows must not assert UT-works metadata content on QA. If a run forgot
   the override, detail pages are slow-but-correct, not broken.
