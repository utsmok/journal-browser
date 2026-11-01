# Deployment

The production deployment is a single docker-compose project in
`docker-compose.yml` with four services: a Postgres database, the FastAPI
backend, a one-shot bootstrap harvester, and the Next.js frontend. The
operations reference behind this page is `DEPLOYMENT.md` at the repo root,
which documents every `.env` variable, the first boot in detail, the deal
register build, and second-institution onboarding. For the development
loop rather than deployment, see
[the development workflow](how-to-contribute/development-workflow.md).

## The four services

| Service | Image source | Ports | Role |
|---|---|---|---|
| `db` | `db/Dockerfile` | `127.0.0.1:5433` | Postgres 17 + pgvector |
| `backend` | `backend/Dockerfile` | `127.0.0.1:8000` | FastAPI app |
| `bootstrap` | `backend/Dockerfile` | none | One-shot harvest pipeline |
| `frontend` | `frontend/Dockerfile` | `0.0.0.0:3000` | Next.js, the public surface |

The `db` image builds pgvector v0.8.7 from source on top of
`postgres:17-alpine`; the Alpine `postgresql-pgvector` package targets the
system Postgres rather than the official image's install, so it cannot be
used. The service sets `shm_size: 512mb` because HNSW index builds need
shared memory beyond the 64 MB container default; the graph for the ~134k
journal vectors peaks around 100 MB. Port 5433 avoids colliding with a
local Postgres on 5432, and `pg_isready` provides the healthcheck.

The `backend` publishes on loopback only: it has no reason to face the
network directly, since the frontend proxies `/api/*` to it. Its
healthcheck calls `GET /api/v1/healthz`, which runs `SELECT 1`, so it turns
green only when the database answers.

`bootstrap` reuses the backend image with `restart: "no"` and runs
`alembic upgrade head` followed by `backend/jobs/bootstrap.py`, the harvest
DAG. The backend declares `condition: service_completed_successfully` on
it, so the API stays down until the pipeline finishes; a failed step keeps
it down, and the logs name the failed step. In the default
`JB_BOOTSTRAP=auto` mode the job exits in seconds once journals exist, so
every `docker compose up` re-runs it harmlessly. `compose.test.yml` shows
the one-shot pattern used to simulate a fresh institute.

The `frontend` is the only service published on `0.0.0.0`, deliberately:
it is the public surface behind the host's reverse proxy. Because
`next build` bakes rewrites into the routes manifest, the proxy target
`API_PROXY_URL` and the citation hostname `NEXT_PUBLIC_SITE_URL` are
build-time arguments; changing them requires a rebuild.

## Volumes and bind mounts

- Named volume `pgdata` holds the database; the Postgres major version
  matches earlier deployments, so the volume carries over unchanged.
- `./backend/landing` is bind-mounted into both `backend` and `bootstrap`:
  raw harvest downloads and job logs must survive container rebuilds.
- `./backend/settings.yaml` is bind-mounted as the admin-editable settings
  overlay (compose pins the file; `backend/docker-entrypoint.sh` replaces
  the empty directory Docker creates on a fresh host with a copy of the
  shipped example).
- `./docs` is mounted read-only at `/app/docs` and served through the
  `/api/v1/docs` endpoints; edits made in the admin panel live in the
  database, not in these files.

The backend image runs as uid 1000 with one exception: the `bootstrap`
service starts as root so `backend/docker-entrypoint.sh` can chown the
freshly created `landing` directory over to uid 1000, then drops
privileges with `setpriv`. Every container start flows through that
entrypoint, so `docker compose run` one-offs never write root-owned files
into the host mount.

## Configuration: the .env lever model

Copy `.env.example` to `.env` and the defaults describe a University of
Twente instance: institution name, short name, ROR id, library and OA
guide URLs, support and admin contacts, the Pure OAI-PMH endpoint, and the
publication-year window (`2020` to open). A new institute edits these
levers and re-runs `docker compose up -d`; no image rebuild is needed
except for `NEXT_PUBLIC_SITE_URL`, which is baked in at build time.
Additional institutions beyond the default are added as rows in the
institutions table, not `.env` entries.

Two other levers matter operationally:

- `backend/settings.yaml` overrides any `.env` value and reloads live, so
  admin-panel edits need no restart; a `.env` variable applies only while
  the YAML lacks that key.
- `JB_ADMIN_PASSWORD` gates the admin panel; empty disables it.

Optional sources stay off by default: `JB_UT_METADATA_DSN` (Twente-only
canonical works accelerator), `JB_OPENAIRE_ORG_ID`, and `OPENALEX_API_KEY`
(needed for the cursor-paged journals sweep). Feature scaffolds
`JB_ENABLE_JISC` and `JB_ENABLE_JOURNAL_CITATIONS` ship OFF.

## First boot and the test stack

Expect the first boot to take 1.5–2 hours, dominated by the OpenAlex
journals sweep (~60 minutes for the ~177k journal universe) and journal
embeddings (~45 minutes on CPU). Budget about 10 GB of disk. Follow the
progress with `docker compose logs -f bootstrap`; the backend only starts
serving once the pipeline succeeds. Later restarts are cheap because
`auto` mode skips the pipeline when journals already exist.

`compose.test.yml` layers `!override` patches onto the base file for a
throwaway stack on its own ports (db 5533, backend 8001, frontend 3001),
its own landing directory, and its own project name (`-p jb-test`). It
pins the publication window to 2025 and empties the ut-metadata DSN to
prove a fresh deployment is self-sufficient. The backend test suite also
expects Postgres at `localhost:5433`, which the production `db` service
conveniently already exposes on loopback.

## Live deployment caution

On this machine the compose project named `journal-browser` is the live
deployment serving ports 3000 and 8000: never restart it, redeploy it, or
write to it. The live `journalbrowser` database is read-only for agents
(`SELECT` is fine, DDL is not). Validate deployment changes against the
test stack instead.

## Related

`.github/dependabot.yml` keeps the Docker and npm dependencies patched, and
CI (`.github/workflows/ci.yml`) gates every change including an alembic
upgrade check against a real database.
