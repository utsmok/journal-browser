# Search

Active contributors: utsmok

Search answering is shared logic: one filtered query builder feeds result
pages, facet counts, and similar-journal lists, and no router copies query
code. This page explains how the backend builds full-text queries, computes
and caches facets, derives journal `oa_type` at query time, and ranks with
pgvector embeddings. The tables behind it are described in
[Data model](data-model.md); the HTTP parameters are documented in
[API surface](../apps/backend/api-surface.md).

## Purpose

Journal search has to feel like one endpoint but serves three consumers:
the results table, the filter panel, and the journal detail page. All
serving-side logic lives under `backend/src/journal_browser/services/`, so
`backend/src/journal_browser/routers/journals.py` and
`backend/src/journal_browser/routers/authors.py` stay thin adapters over
it.

![Search results for "water" with the filter panel](images/web-search-results.png)

![Semantic "match by meaning" search over journal embeddings](images/web-semantic-search.png)

## Directory layout

- `backend/src/journal_browser/services/search/` - the journal search package:
  - `backend/src/journal_browser/services/search/query.py` - `base_query`, sort keys, APC display
  - `backend/src/journal_browser/services/search/core.py` - `search_journals` page assembly
  - `backend/src/journal_browser/services/search/facets.py` - `facet_counts`
  - `backend/src/journal_browser/services/search/classify.py` - the `oa_type` decision tree
  - `backend/src/journal_browser/services/search/cursors.py` - cursor encode/parse
  - `backend/src/journal_browser/services/search/similar.py` - `semantic_search`, `similar_journals`
  - `backend/src/journal_browser/services/search/currency.py` - EUR conversion rates
- `backend/src/journal_browser/services/cache.py` - the in-process TTL caches
- `backend/src/journal_browser/services/facets.py` - author, org-unit, and publisher facets (drop-own-dimension rule)
- `backend/src/journal_browser/services/authors.py` - author roster search and profiles
- `backend/src/journal_browser/services/works_query.py` - shared author-works query fragments
- `backend/src/journal_browser/services/embeddings.py` - embedding text construction and query encoding
- `backend/src/journal_browser/services/detail_enrichment.py` - journal works tab and per-journal metrics
- `backend/src/journal_browser/services/flags_refresh.py` - background deal-flag recompute after admin writes
- `backend/src/journal_browser/harvest/denorm.py` - the refreshes that maintain search state
- `backend/tests/test_search_scopes.py` - the search contract tests

## Key abstractions

| Abstraction | Home | Role |
|---|---|---|
| `base_query` | `backend/src/journal_browser/services/search/query.py` | One filtered select with computed columns; shared by search, facets, and similar lists |
| `search_journals` | `backend/src/journal_browser/services/search/core.py` | Page assembly: fuzzy retry, keyset paging, APC display, facet pass |
| `facet_counts` | `backend/src/journal_browser/services/search/facets.py` | One-pass facet aggregates over the filtered base |
| `FACET_CACHE` + `cache_epoch` | `backend/src/journal_browser/services/cache.py` and `backend/src/journal_browser/harvest/common.py` | In-process facet cache keyed on the harvest epoch |
| `parse_cursor` / `encode_cursor` | `backend/src/journal_browser/services/search/cursors.py` | Opaque base64 keyset cursors; malformed input raises `ValueError` (mapped to 400) |
| `_oa_type` / `oa_type_value` | `backend/src/journal_browser/services/search/classify.py` | SQL case and Python mirror of the query-time OA classification |
| `semantic_search` / `similar_journals` | `backend/src/journal_browser/services/search/similar.py` | pgvector cosine ranking plus shared-topic fallback |
| `encode_query` | `backend/src/journal_browser/services/embeddings.py` | fastembed ONNX query encoding |
| `author_facets` | `backend/src/journal_browser/services/facets.py` | Author facet counts, each dropping its own filter |
| works-query fragments | `backend/src/journal_browser/services/works_query.py` | Author-works joins, window bounds, and strata shared by every consumer |

## How it works

### Query building

`base_query` always joins the scoped institution's `journal_flags` rows, so
the per-institution corpus cutoff (`works_window_plus > 3`), the
`browse_excluded` exclusion, and per-institution deal coverage apply to
every consumer. It also drops the admin ignore-list (read from settings at
call time, so admin edits land live) and restricts to `journals.type =
'journal'`.

The computed select list carries what every consumer needs: the two-year
citedness metric cast to numeric, the primary topic (the first entry of the
topics array), a display APC price (OpenAlex EUR list price, then USD, then
the denormalized `latest_apc_euro`), the `oa_type` case, and the relevance
rank.

Full-text matching uses `websearch_to_tsquery('english', q)` against the
generated `search_vector` column, plus a case-insensitive prefix match on
`search_text`. ISSN queries normalize the input (hyphens, spaces, case) and
match `journals.issn_l` directly or resolve any print/online variant
through `issn_map`.

The relevance rank is one expression so keyset pagination can compare
tuples of it: a title-prefix tier worth 100.0, the `ts_rank` score, and a
small prominence nudge from `works_count`. The tier spacing guarantees
title matches sort before everything else.

### Search scopes

`search_in` accepts `all`, `title`, `publisher`, or `topic` (validated at
the router). The `title` scope applies the FTS, prefix, and ISSN
conditions; `publisher` applies an escaped substring `LIKE` over the
publisher name; `topic` applies a case-insensitive match over the topics
column through its trigram expression index. Topic stays an explicit scope
because folding it into the `all`-scope `OR` forced a sequential scan.
`backend/tests/test_search_scopes.py` pins each scope's behavior, along
with ISSN normalization, the fuzzy fallback, cursor behavior, facet
variants, proceedings exclusion, and `oa_type`.

### Fuzzy fallback

When a query pass returns zero rows, `search_journals` probes with
`LIMIT 1` (cheaper than a full count before a retry) and rebuilds the query
with the trigram similarity operator over `search_text` at pg_trgm's
default threshold (0.3). The response sets `fuzzy: true`, the facet counts
recompute over the fuzzy set, and the total comes from the fuzzy subquery
itself.

### Sorting and cursor pagination

Eight sort keys exist: `relevance`, `title`, `publisher`,
`institution_works`, `quartile`, `topic`, `apc`, and `2yr_mean_citedness`.
Paging is keyset-based on the tuple `(order value, issn_l)`, so inserts
never shift pages. Numeric sorts (`relevance`, `institution_works`,
`2yr_mean_citedness`, `apc`) cast the cursor value to `Numeric` in both
directions; text sorts cast to `String`. The cursor value is read from a
database-computed labeled column so it matches the sort collation exactly.
The cursor itself is base64 JSON; a malformed one raises `ValueError`,
which the app maps to 400.

Page turns pass `include_facets=false`, skipping both the facet aggregate
and the duplicate count, because facets depend only on the filter set and
the previous response already carried the total.

APC display fields are stamped per page by `attach_apc_display` (two keyed
queries, never a lateral join per row): an OpenAlex list price wins,
standardized to EUR at the January 1 rate of the current year
(`backend/src/journal_browser/services/search/currency.py`); otherwise the
OpenAPC observed range over
the newest two evidence periods, with per-period stats for the tooltip.

### Facets

`facet_counts` evaluates the filtered base exactly once: window counts
(partitioned by `oa_type` and publisher) turn the histograms into plain
aggregates, and `count(...)` filter columns produce the boolean facets
(deal coverage, OA, DOAJ, quartile, APC, works). The topic histogram runs
as its own statement because exploding roughly 130k topic arrays would
dominate the shared aggregate. Chip counts follow the drop-own-filter rule:
each active facet's own filter is dropped for its variant pass, so a chip
shows what selecting it would yield under the remaining filters.

### Facet cache and cache-epoch invalidation

Unfiltered browse facets are identical for every visitor until the next
harvest, so they cache in-process in `FACET_CACHE`
(`backend/src/journal_browser/services/cache.py`)
under a key combining the institution id, a hash of the admin ignore-list,
and the current harvest epoch. Entries live up to 24 hours, but any epoch
bump invalidates on the next request.

The epoch lives in the single-row `cache_epoch` table.
`backend/src/journal_browser/harvest/common.py` reads it (`cache_epoch`)
and stamps it (`bump_cache_epoch`). It is bumped by:

- every completed harvest run (the shared run wrapper in
  `backend/src/journal_browser/harvest/common.py`),
- each denormalization refresh (works stats, quartiles, APCs, deal flags)
  in `backend/src/journal_browser/harvest/denorm.py`,
- the publisher-lineage backfill in
  `backend/src/journal_browser/harvest/publishers.py` when it updates
  journals.

Admin deal writes return instantly but schedule
`backend/src/journal_browser/services/flags_refresh.py`, which recomputes
each hosted institution's deal flags on a fresh connection in the
background (rerunning once if a pass was already in flight) and bumps the
epoch per refresh. Coverage therefore lags an admin edit by seconds, and
facet caches rebuild on the next request after it.

### The oa_type decision tree

Journal-level `oa_type` is never stored; the SQL `case` in
`backend/src/journal_browser/services/search/classify.py` derives it per
row, and `oa_type_value` mirrors it in Python for the detail endpoint. In
order:

1. `gold`: OA evidence (`is_in_doaj`, `is_oa`, or `doaj_in_doaj`) plus
   charge evidence (`doaj_has_apc`, any OpenAPC aggregate row,
   `latest_apc_euro`, or an OpenAlex `apc_prices` entry).
2. `diamond`: DOAJ-listed with `doaj_has_apc = false` (DOAJ's explicit
   no-APC declaration is the canon).
3. Observed color: `oa_status_observed` in gold, diamond, or hybrid.
   Bronze, closed, and green observations mean "no OA color observed" and
   fall through rather than produce an overeager diamond.
4. `hybrid`: the journal is deal-covered for the scoped institution.
5. `generic`: OA evidence with no OA-model evidence at all.
6. `subscription`: everything else.

The `oa_type` facet multi-selects these values with OR semantics, and the
router validates the comma-separated parameter against the vocabulary.

### Semantic search and similar journals

Vectors live in `journals.embedding`: 384 dimensions from
`BAAI/bge-small-en-v1.5`, written by `backend/jobs/embed_journals.py` from
the cleaned title, the top five topics, and three most-cited work titles
(`embed_text` in `backend/src/journal_browser/services/embeddings.py`).
Query encoding uses fastembed (ONNX on CPU, no torch), lazily loading the
roughly 130 MB model on first call and running in a worker thread so
inference never stalls the event loop. fastembed's query prompt applies at
query time while stored passages stay unprefixed, per the BGE recipe.

Ranking orders by cosine distance through pgvector's HNSW index with
`hnsw.iterative_scan = strict_order`, so filtering keeps exact distance
order and the scan iterates past `ef_search` until enough rows pass the
filters. For semantic search, `ef_search` scales with paging depth; the
response rows match `search_journals` items so the frontend table renders
them unchanged. Paging uses a plain decimal offset cursor that is only
meaningful for the query that produced it, which matches the frontend's
contract of resetting on query changes.

`similar_journals` returns three cutoff-passing lists per journal:
`institution` (at least one known institution publication) and `deals`
(deal-covered), each capped at 5, and `all` capped at 10. Journals without
an embedding, or with a degenerate zero vector, fall back to shared-topic
ranking with the same three scopes.

### Author search

`backend/src/journal_browser/routers/authors.py` delegates to
`backend/src/journal_browser/services/authors.py`: a roster query over
`authors` with `|`-separated multi-selects (faculty, org, topic, works
strata, last-publication buckets), offset pagination, and facet counts from
`backend/src/journal_browser/services/facets.py`, each dimension dropping
its own filter. `institutions.require_confirmed_affiliation` gates the
search list to confirmed authors while profiles stay accessible. Every
work-count and year-window condition goes through the shared fragments in
`backend/src/journal_browser/services/works_query.py`, and author-profile
journal suggestions reuse `base_query` plus the shared `oa_type` case, so
corpus cutoffs and exclusions apply identically.

### Detail enrichment

The journal works tab and per-journal metrics read the landing store
directly through `backend/src/journal_browser/services/detail_enrichment.py`:
the latest version of each OpenAlex work payload (`DISTINCT ON` per source
key from `source_records`), filtered before detoast through the mirrored
`publication_year` column and bounded to the institution's data window.
OpenAIRE match counts come from confirmed `work_identity` rows.

## Integration points

- Endpoints: `GET /api/v1/{code}/journals`,
  `/journals/semantic-search`, `/journals/{issn_l}/similar`,
  `/journals/{issn_l}/works`, and `/journals/{issn_l}` in
  `backend/src/journal_browser/routers/journals.py`; the author endpoints
  in `backend/src/journal_browser/routers/authors.py`.
- Harvest writes the state search reads (flags, quartiles, APCs,
  embeddings); see [Data pipeline](data-pipeline/index.md).
- The schema behind every query (flags, ISSN map, evidence tables) is in
  [Data model](data-model.md).
- Frontend response types are generated from the OpenAPI schema; any new
  parameter or field requires the type refresh described in
  [Backend](../apps/backend/index.md).

## Entry points for modification

1. New filter: add a `base_query` parameter, a router `Query` parameter, a
   facet variant in `facet_counts`, and regenerate the API types.
2. New sort key: add a `_order` branch, include it in `NUMERIC_SORTS` if
   the column is numeric, and cover the cursor cast in
   `backend/tests/test_search_scopes.py`.
3. New facet: add the aggregate pass and its drop-own-filter variant in
   `facet_counts`.
4. Changed embedding model: update `backend/src/journal_browser/services/embeddings.py`
   and `backend/jobs/embed_journals.py` together, then re-embed every
   journal so vectors stay comparable with query encodings.
5. New denormalized search column: pair it with a refresh statement and an
   epoch bump so caches invalidate (see
   `backend/src/journal_browser/harvest/denorm.py`).

## Key source files

| File | Contents |
|---|---|
| `backend/src/journal_browser/services/search/query.py` | `base_query`, sort keys, `attach_apc_display` |
| `backend/src/journal_browser/services/search/core.py` | `search_journals` page assembly and fuzzy retry |
| `backend/src/journal_browser/services/search/facets.py` | `facet_counts` and the facet cache |
| `backend/src/journal_browser/services/search/classify.py` | The `oa_type` SQL case and Python mirror |
| `backend/src/journal_browser/services/search/cursors.py` | Cursor encode/parse |
| `backend/src/journal_browser/services/search/similar.py` | `semantic_search`, `similar_journals` |
| `backend/src/journal_browser/services/cache.py` | In-process TTL stores |
| `backend/src/journal_browser/services/embeddings.py` | Query encoding and embedding text construction |
| `backend/src/journal_browser/services/facets.py` | Author and org-unit facets |
| `backend/src/journal_browser/services/works_query.py` | Shared author-works fragments |
| `backend/src/journal_browser/services/flags_refresh.py` | Background deal-flag recompute |
| `backend/src/journal_browser/harvest/denorm.py` | Denormalization refreshes and epoch bumps |
| `backend/src/journal_browser/routers/journals.py` | Journal search and detail endpoints |
| `backend/src/journal_browser/routers/authors.py` | Author search and profile endpoints |
| `backend/tests/test_search_scopes.py` | The search contract tests |
