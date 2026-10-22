# Prior art: reusable patterns from the owner's own repositories

Mined 2026-10-22 (utsmok on GitHub). Two generations of the same async-client skeleton
exist (AIREloom → stavrophora, both on `bibliofabric`); `openalex_vs_scival` is the
raw-HTTP reference for OpenAlex itself. An OpenAlex client = stavrophora's structure +
openalex_vs_scival's pagination/batching.

## utsmok/openalex_vs_scival (2025-10, marimo notebook, ~430 lines)

- Purpose: compare OpenAlex works/topics metadata against SciVal exports (~14k DOIs,
  merged in <5 min at 1 req/s).
- Stack: marimo, httpx + httpx-limiter (`AsyncRateLimitedTransport`), polars, uv, Python 3.13.
- Query recipe (`main_code.py`): cursor pagination — start `cursor=*`, follow
  `meta.next_cursor`; `per-page=200` (max at the time); `select=` field projection;
  `data-version=2`.
- ID batching: OR-filter syntax `filter=doi:A|B|C`, chunked ≤50 — OpenAlex caps
  filter-list length (now 100).
- Extras: polite pool via email UA; DOI-normalizer regex; polars struct-unnest for
  `open_access`/`primary_topic`/`topics`; SciVal↔OpenAlex join on standardized DOI.
- **Worth copying:** the fetch function (cursor loop + batched OR-filters + select) as
  the ingestion seed. **Worth avoiding:** the chunked-filter branch reuses a loop
  variable — keep that logic in one tested helper, not notebook cells.

## utsmok/MUS (Django portal, MIT, live at openalex.samuelmok.cc)

- Purpose: institutional research-output browser — ingest from OpenAlex, Pure (OAI-PMH),
  OpenAIRE, Crossref, DataCite; browse, analyze, export CSV/CERIF.
- Stack: Django + SQL with MongoDB as raw-response landing zone; **`pyalex` for
  OpenAlex**; Docker + Caddy; loguru.
- Data flow: fetchers dump raw JSON into Mongo collections → batch-normalize into SQL
  models (500–1000/batch, per-item try/except, added/failed ID lists, one audit row per
  run) → query layer → exports.
- **Worth copying:** two-stage ingestion (raw landing zone → normalized tables) so schema
  changes never force re-fetching; dedupe on DOI/OpenAlex ID for idempotent runs; pyalex
  retry config (`max_retries=5`, backoff 0.4, retry 429/500/503).
- **Worth avoiding:** 78 KB single-module query layer; Mongo+SQL dual persistence glue —
  a journal browser needs one store plus a raw cache.

## utsmok/stavrophora (async Crossref client on bibliofabric, MIT, v0.2.1)

- Layout: `src/stavrophora/` — `client.py` (`BaseApiClient` subclass with lazy
  resource-client properties), `config.py` (pydantic-settings), `endpoints.py` (Pydantic
  filter models), `models/`, `resources/` (standard base + one thin client per entity).
- The pattern: override `_serialize_filters` to emit API filter syntax;
  `_batch_fields` + `__init_subclass__` auto-generates `batch_get_by_*` (batch size 50);
  cursor `iterate()` with resume-cursor, `on_error`/`on_page` hooks; parse failures fall
  back to raw dict; response-envelope Unwrapper injected at client level.
- Tests: pytest + pytest-httpx mocks; `live_api` marker excluded by default; ruff strict,
  pre-commit, py.typed.
- **Worth copying:** file-for-file as the OpenAlex-client template — swap
  `_serialize_filters` for OpenAlex `filter=a:b,c:d` + `select` + `sort`, cursor
  pagination per openalex_vs_scival.

## utsmok/AIREloom (async OpenAIRE client on bibliofabric, MIT, on PyPI)

- Same skeleton, mature/published: `session.py`, `endpoints.py` (ENDPOINT_DEFINITIONS +
  filter models), `resources/` (standard base + `_batch.py`), `models/`, `queries.py`
  convenience layer, `unwrapper.py`.
- Best-in-class method surface per resource: `get / search / iterate / collect / count /
  first` — adopt verbatim for a sources/works client.
- Ergonomics: computed properties (`doi`, `publication_year`, `is_open_access`),
  SafeStr/SafeList, hooks, optional caching, Retry-After rate-limit handling.
- Lessons: documents upstream API quirks in-repo (`OPENAIRE_BUG_REPORT.md`) — OpenAlex
  has similar quirks (see openalex.md §1 note); keep a quirks doc.
- **Worth avoiding:** repo-root clutter with report dumps; one 43 KB test module.
