# Security

Open Journal Browser is a public-read tool deployed on a trusted network and
published through a host reverse proxy. It has no user accounts: every
visitor shares one unauthenticated read surface, and one shared password
guards the admin API. This page states the actual boundaries and mechanisms
so nobody has to reverse-engineer them from the code.

## Network boundaries

The compose file (`docker-compose.yml`) publishes exactly one container to
the outside:

| Service | Published as | Reachable from |
|---|---|---|
| frontend | `3000:3000` (all interfaces, on purpose) | anyone who can reach the host |
| backend | `127.0.0.1:8000:8000` | the host only |
| db | `127.0.0.1:5433:5432` | the host only |

The frontend is the public surface and is meant to sit behind the host's
reverse proxy (TLS termination lives there, not in the stack). It proxies
`/api/*` to the backend over the internal compose network
(`API_PROXY_URL`), so direct API access requires a shell on the host. The
Postgres port is mapped to host loopback on 5433 so dev tools and test
stacks do not collide with a local 5432. The database credentials
(`journal`/`journal`) are compose defaults; the loopback binding is the
actual control, not the password strength.

CORS is the one HTTP-level control: `backend/src/journal_browser/main.py`
adds `CORSMiddleware` with `allow_origins=settings.cors_origins` (default
`["http://localhost:3000"]`, editable as a global admin setting; changes
need a restart) and wildcard methods and headers. It shapes which browser
origins may call the API from JavaScript; it is not an authentication
layer.

## Public read surface vs admin surface

Unauthenticated read endpoints cover the institution listing, per-institution
search and detail routes under `/api/v1/{code}/`, docs, health, and the
feedback intake form (public by design; see
[Feedback](features/feedback.md)). Anyone on the network can read all data
and submit feedback.

Everything under `/api/v1/admin` requires a bearer token. The frontend
admin panel (`frontend/app/admin/`) is convenience only; the API is the
boundary. See [Admin panel](features/admin.md) for what the panel does.

## Admin authentication

The whole model lives in one small module,
`backend/src/journal_browser/routers/admin/auth.py`:

- The password is the `admin_password` setting (`JB_ADMIN_PASSWORD`, or the
  `backend/settings.yaml` overlay). When it is empty, admin is disabled:
  login and every guarded endpoint return 403 with
  `admin disabled: set JB_ADMIN_PASSWORD`.
- `POST /api/v1/admin/login` compares the submitted password with
  `hmac.compare_digest` and issues a stateless token `{expires}.{mac}`,
  where `mac` is HMAC-SHA256 over the expiry timestamp, keyed by
  `sha256("jb-admin:" + password)`.
- The token is valid for 12 hours (`TOKEN_TTL`). Validation recomputes the
  MAC and uses `hmac.compare_digest`, so the expiry cannot be edited
  without breaking the MAC.
- Every admin endpoint depends on `AdminDep`, which rejects missing,
  malformed, and expired tokens with 401. Because the key derives from the
  current password, changing the password invalidates all outstanding
  tokens immediately.

There is no lockout, brute-force throttling, or server-side session: the
12-hour TTL and password rotation are the only revocation story. The
frontend keeps the token in `sessionStorage`, so it dies with the tab.

## Secrets handling

Secrets exist in three places, each with its own rule:

1. **Environment.** `JB_*` variables (`.env` in compose) are the
   deployment-level source: database DSN, `JB_ADMIN_PASSWORD`,
   `OPENALEX_API_KEY`, `JB_JISC_API_KEY`, `JB_UT_METADATA_DSN`. They are
   never served by any endpoint.
2. **The settings overlay.** `backend/settings.yaml` (bind-mounted into
   the backend container, writable because the admin PUT writes it) wins
   over env values and reloads live on mtime change
   (`backend/src/journal_browser/config.py`).
3. **The admin settings API.** `backend/src/journal_browser/settings_schema.py`
   declares which fields are secrets (`admin_password`, `openalex_api_key`,
   `jisc_api_key`, `ut_metadata_dsn`). `GET /admin/settings` returns the
   mask `********` (or null when unset) instead of the stored value, and a
   PUT that sends the mask or an empty string keeps the current value, so
   form round-trips cannot wipe a key.

`database_url` is deliberately absent from the editable registry: a boot
dependency with credentials in the DSN must not be changeable at runtime.
The `docs/` bind mount is read-only (`./docs:/app/docs:ro`), so the app
cannot modify served doc sources; doc edits live in the database instead.

## Injection and input validation

All queries go through SQLAlchemy 2 (async) with bound parameters; jobs and
routers build statements with ORM/Core constructs rather than string
interpolation, and the few literal SQL fragments (for example the `SELECT 1`
in the health check and CHECK-constraint DDL) carry no user input.

Validation happens at the edges: pydantic models validate request bodies
(FastAPI answers 422 on shape errors), query parameters carry explicit
bounds (for example `limit` is capped at 500 on the admin runs endpoint),
and an app-level exception handler maps `ValueError` to 400, which is how
malformed cursors and similar bad input fail cleanly. Institution codes are
validated against `[a-z0-9-]+` before they ever reach a query.

## Deliberately out of scope

This is a LAN-deployed proof of concept, and the posture says so:

- No user accounts, roles, or per-user audit trail. One shared admin
  password is the entire access model.
- No rate limiting or request throttling anywhere in the app.
- No brute-force protection or lockout on the login endpoint.
- No TLS inside the stack; the host reverse proxy owns that.
- No secret-rotation tooling beyond editing the env or the overlay.

Treat the host network as the security perimeter. If the deployment ever
moves off a trusted LAN, every item in this list becomes work.
