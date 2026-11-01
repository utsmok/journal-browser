# Dependencies

Derived from `backend/pyproject.toml` and `frontend/package.json`. The
backend is managed with `uv`, the frontend with npm; never install with
bare `pip` or edit the lockfiles by hand.

## Backend runtime dependencies

| Package | Purpose |
|---|---|
| `fastapi` | API framework: routers, request validation, the OpenAPI schema. |
| `uvicorn[standard]` | ASGI server that runs the app. |
| `sqlalchemy[asyncio]` | ORM and async engine; the whole schema is SQLAlchemy 2 declarative models. |
| `asyncpg` | Async Postgres driver under SQLAlchemy. |
| `pydantic-settings` | Environment-driven `Settings` in `backend/src/journal_browser/config.py`. |
| `alembic` | Schema migrations in `backend/alembic/versions/`. |
| `pgvector` | `Vector` column type for the 384-dim journal embeddings. |
| `fastembed` | Local ONNX embedding model (BAAI/bge-small-en-v1.5); the ~130 MB preload `JB_SKIP_EMBEDDING_WARMUP` skips. |
| `httpx` | Async HTTP client for source fetches. |
| `bibliofabric` | Foundation library shared by the three scholarly clients below (same author). |
| `aletheca` | OpenAlex client: journal sweep, works, publisher lineage, ISSN map. Also reads `ALETHECA_OPENALEX_API_KEY`. |
| `aireloom` | OpenAIRE client: DOI confirmations and person ids. |
| `stavrophora` | Crossref client: the fallback rung of the enrichment ladder. |
| `openpyxl` | Reads Excel workbooks, for example the Emerald contract ingestion job. |
| `beautifulsoup4` | HTML/XML parsing of harvested pages and payloads. |
| `lxml` | Fast XML/HTML parser backend alongside beautifulsoup4. |
| `pyyaml` | Reads and writes the `backend/settings.yaml` overlay. |
| `currencyconverter` | Converts APC prices to EUR in `backend/src/journal_browser/services/search/currency.py`. |
| `nameparser` | Person-name parsing in `backend/src/journal_browser/harvest/author_names.py`. |
| `levenshtein` | Fuzzy name similarity in the author identity cascade. |

The three clients (`aletheca`, `aireloom`, `stavrophora`) are same-author
libraries built on `bibliofabric`, so their request and pagination behavior
stays consistent across OpenAlex, OpenAIRE, and Crossref.

## Backend dev group

| Package | Purpose |
|---|---|
| `pytest` | Test runner; the `live` marker gates network-hitting tests. |
| `pytest-asyncio` | Async test support (`asyncio_mode = "auto"`). |
| `ruff` | Linter and formatter (line length 100). |
| `ty` | Alpha type checker; framework-idiom warnings are demoted in `pyproject.toml`. |

## Frontend dependencies

| Package | Purpose |
|---|---|
| `next` (15) | App Router framework; serves the per-institution pages. |
| `react`, `react-dom` (19) | UI runtime. |
| `@tanstack/react-query` | Server-state caching for all API calls. |
| `@tanstack/react-table` | Search results table. |
| `tailwindcss` (4) | Styling, via the PostCSS plugin. |
| `lucide-react` | Icon set. |
| `mermaid` | Client-side rendering of diagrams in served docs (`frontend/components/docs/mermaid-block.tsx`). |
| `clsx`, `tailwind-merge`, `class-variance-authority` | Class composition and component-variant helpers. |

Dev dependencies: `@biomejs/biome` (formatter, the only formatter),
`eslint` with `eslint-config-next` (linter), `openapi-typescript` (generates
`frontend/lib/api-types.ts` from `../openapi.json` via `npm run generate`),
`typescript`, and the matching `@types/*` packages.

## External services

The harvest pipeline calls these openly available sources. Jobs are
idempotent and fail by naming their step, so a down service stops the
bootstrap DAG at that step and the repair flags (`--from`, `--institution`,
`--always`) re-run it later.

| Service | Used for | If it is down |
|---|---|---|
| OpenAlex | Journal universe sweep, works stats, per-author enrichment, publisher lineage, ISSN map. | The global journal layer cannot build; keyed cursor-paged harvests also degrade without `OPENALEX_API_KEY`. |
| OpenAIRE | DOI confirmations and person ids for the institution layer. | Confirmation counts fall; empty `JB_OPENAIRE_ORG_ID` disables this harvest by design. |
| Crossref | Enrichment fallback when OpenAlex lacks a DOI match; `crossref_meta` on journals. | The enrichment ladder marks records unresolved; candidates route to curation. |
| Pure OAI-PMH | The institution's works corpus and CERIF entities (orgs, persons). | The per-institution layer fails; the shared journal and deal core still builds. |
| DOAJ | Authoritative journal OA canon (`doaj_*` columns). | Columns stay NULL; `oa_type` classification falls back to deal and subscription logic. |
| OpenAPC | Per-article APC cost evidence. | `latest_apc_euro` and the cost aggregates go stale or empty. |
| Scimago | SJR, quartiles, h-index; CSVs land in the landing zone (`landing/scimagojr/`). | Quartile columns stay empty; search facets degrade. |
| openaccess.nl | The deal register the deals layer is built from. | No deals are ingested; the deals pages stay empty. |
| JCT/ESAC | Deal enrichment (cap numbers, JCT data URLs, participation). | Deals keep register data but lose JCT fields; `needs_curation` flags the gaps. |

The optional ut-metadata Postgres (behind `JB_UT_METADATA_DSN` and
`author_source=utmd`) is a self-hosted accelerator, not an external
service; unset, nothing depends on it.

## Toolchain requirements

| Requirement | Where it applies |
|---|---|
| Python 3.12 | Backend, managed with `uv`. |
| Node 22+ | Frontend builds and `npm run generate`. |
| Postgres 17 with pgvector | The only serving database; custom image in `db/`. |
| Docker Compose v2.24+ | Deployment and test stacks; the test and per-institute overrides use newer compose features. |

## Related pages

Getting a stack running is covered in
[Getting started](../overview/getting-started.md); what each external
source contributes to the data is detailed in
[Harvest sources](../systems/data-pipeline/harvest-sources.md), and the
type pipeline that links the OpenAPI schema to the frontend is in
[API surface](../apps/backend/api-surface.md).
