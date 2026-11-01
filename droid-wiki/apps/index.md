# Apps

Active contributors: utsmok

Journal Browser ships two deployable applications that share one Postgres
database. The frontend proxies every `/api/*` request to the backend, so the
backend is never exposed publicly; see
[Architecture](../overview/architecture.md).

| App | What it runs | Wiki page |
|---|---|---|
| Backend | FastAPI API on port 8000: the `/api/v1` surface, the settings system, and the packages the harvest jobs import | [Backend](backend/index.md) |
| Frontend | Next.js 15 UI on port 3000: per-institution pages under `app/[inst]/`, the global admin panel, and the generated API client | [Frontend](frontend/index.md) |

Both apps are containerized in `docker-compose.yml`. The database is filled
before the backend starts by the one-shot `bootstrap` service, whose jobs are
covered in [Data pipeline](../systems/data-pipeline/index.md) rather than on
the app pages.
