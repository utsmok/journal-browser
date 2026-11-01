# API

The backend exposes one REST API under `/api/v1`, built with FastAPI in
`backend/src/journal_browser/main.py`. The frontend never talks to the
backend directly: Next.js rewrites in `frontend/next.config.mjs` proxy
`/api/*` to the backend service (`API_PROXY_URL` in compose), so the browser
only ever sees the frontend origin. The endpoint-by-endpoint reference lives
in [Endpoints](endpoints.md); this page covers how the surface is shaped.

## Global versus institution-scoped

The router tree in `backend/src/journal_browser/main.py` splits the surface
in two:

- Global routers exist once per deployment: `institutions` (the hosted
  institution directory), `admin` (the password-gated panel), `feedback`
  (anonymous intake), `docs` (markdown serving), and `healthz`.
- One institution-scoped router is mounted at `/{institution_code}` and
  carries the six per-university resource families: `journals`, `authors`,
  `publishers`, `orgunits`, `deals`, and `meta`. Every scoped handler
  resolves the path code against the institutions table and returns 404 for
  an unknown code.

Registration order is part of the contract: `admin`, `feedback`, and `docs`
are included before the scoped router so fixed prefixes such as
`/api/v1/admin/deals` are not captured by the `/{institution_code}`
catch-all. The patterns behind this split are described in
[API surface](../apps/backend/api-surface.md).

## Response conventions

- List endpoints paginate with an opaque `cursor` parameter and return a
  `next_cursor` field for the following page (journals search and semantic
  search). Authors, publishers, and orgunits use plain `offset`/`limit`
  paging instead.
- Malformed pagination or query input raises `ValueError` inside handlers;
  an app-level exception handler maps it to HTTP 400 with the message as
  `detail`. FastAPI's own boundary validation of typed parameters still
  returns 422, so the two statuses separate "your cursor is broken" from
  "your parameter failed schema validation".
- Detail responses carry per-field source attribution, with caveat codes
  that resolve against the limitations registry served at
  `GET /api/v1/{code}/meta/limitations`.
- CORS is enabled through FastAPI's `CORSMiddleware` with origins from
  `settings.cors_origins`, all methods and headers allowed.

## Small, fixed endpoints

`GET /api/v1/healthz` executes `SELECT 1` against the database and returns
the application version; the compose backend healthcheck targets it. The
`docs` family serves the repository's markdown files as parsed blocks:
`GET /api/v1/docs` lists available documents and `GET /api/v1/docs/{slug}`
returns block-keyed text with any admin `doc_edits` overrides applied at
read time, so the frontend's per-institution docs pages show edited copy
without touching the source files.

## Machine-readable schema

The schema is committed at `openapi.json` (42 operations across 36 paths as
of 2026-10-31). After any backend API change, `backend/scripts/dump_openapi.py`
regenerates it and `npm run generate` in `frontend/` refreshes
`frontend/lib/api-types.ts`, the TypeScript client types; CI regenerates the
schema and fails if the committed file drifted. This pipeline is why
frontend code and backend responses stay type-aligned without hand-written
interfaces.
