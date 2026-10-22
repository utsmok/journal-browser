# Improvement sweep — 2026-10-22

A fresh-eyes audit of the working product. Unlike the concurrent plan-vs-implementation
review, this sweep did not compare against `docs/plan.md` or the live WUR journal browser.
It looked for bugs, performance problems, data-handling risks, UX gaps, and stack issues
on their own terms.

## Method and how to re-verify

- Five parallel read-only audits (backend queries/DB, frontend UX, data pipeline,
  stack/tests, external patterns), each returning file:line evidence.
- Live measurement against the running compose stack: `curl` timings, `EXPLAIN
  (ANALYZE, BUFFERS)` on the exact statements the search service issues (captured by
  wrapping `session.execute`), and a headless-browser session driving the real UI at
  `localhost:3000` (desktop 1440px and mobile 390px).
- Every finding below is labeled: **[live]** (reproduced against the running stack),
  **[code]** (file:line evidence, not executed), or **[inference]** (reasoned, not
  measured).
- Row counts in this report were measured on the live DB: 177,181 journals, 138,897 in
  the default quality scope.

## Priority table

| # | Finding | Area | Impact | Effort | Ref |
|---|---------|------|--------|--------|-----|
| 1 | JCT re-ingest overwrites canonical curated deals and leaks the wrong publisher's journal list | Data | H | M | C1 |
| 2 | openaccess.nl scrape clobbers curation flags and provenance | Data | H | M | C2 |
| 3 | Topic filter 500s on every click (`jsonb @> varchar`) | Bug | H | S | A1 |
| 4 | "Deal coverage" facet chips filter nothing | Bug | H | S | A2 |
| 5 | No FTS/trigram indexes; every search seq-scans 177k rows (measured 2-3s) | Perf | H | S | B1 |
| 6 | Search list double-counts UT works (45 shown, 22 real) | Bug | H | S | A4 |
| 7 | Facet counts ignore the active deal/topic filter | Bug | M | S | A3 |
| 8 | Three correlated per-row subqueries evaluated for the whole corpus | Perf | H | M | B2 |
| 9 | Three divergent definitions of "Twente deal-covered" | Data | H | S | C3 |
| 10 | OpenAIRE title match missing its trigram index; job will not finish | Data | H | S | C4 |
| 11 | Keyset cursor encodes NULL → empty next page | Bug | M | S | A5 |
| 12 | Filter changes refetch with a stale page cursor | Bug | M | S | D2 |
| 13 | Default browse-all sort is meaningless; landing page shows zero-data journals | UX | M | S | D1 |
| 14 | Scimago ingest creates thousands of title-less ghost journals | Data | M | S | C5 |
| 15 | No gzip/ETag/Cache-Control on any endpoint | Perf | M | S | B4 |
| 16 | `npm run lint` is broken; nothing lints | Stack | M | S | E1 |
| 17 | Test suite silently skips ~30-45% without a DB | Stack | M | S | E4 |
| 18 | `.env` not dockerignored; secrets can bake into images | Stack | M | S | E3 |
| 19 | Tooltip provenance links are unclickable | UX | M | S | D3 |
| 20 | Brand orange fails WCAG AA as text color | UX | M | S | D4 |
| 21 | No per-page document titles | UX | M | S | D5 |
| 22 | Raw API error strings are user-facing copy | UX | M | S | D6 |
| 23 | Header nav uses `<a>`, full reloads every navigation | UX | M | S | D7 |
| 24 | Scimago/OpenAPC ISSN handling weaknesses (no checksum, print/online) | Data | M | S | C6, C7 |
| 25 | openaccess.nl deals never retire; natural key fragile | Data | M | M | C9 |

Everything else (P2): copy and a11y polish, pool tuning, ingest batching, compose
hardening, feature ideas. Details per section below.

## A. Correctness bugs (broken behavior today)

**A1. The topic filter 500s on every request. [live]**
Clicking any topic chip on the search page shows "API 500 on /journals". Backend log:
`journals.topics @> $7::VARCHAR` — asyncpg binds the containment value as `VARCHAR`
against a `jsonb` column, so Postgres rejects the operator. The filter has probably never
worked. Fix in `base_query` (`backend/src/journal_browser/services/search.py:156`): pass
the JSON literal as a `JSONB`-typed literal, e.g.
`Journal.topics.op("@>")(cast(literal(json_string), JSONB))`. One line.

**A2. The "Deal coverage" / "No deal" chips do nothing. [live]**
Clicking them writes `?deal_coverage=covered` and the result count stays 138,897. The
chips' URL key is `deal_coverage` (`frontend/app/page.tsx:291-298`) but the query builder
reads `deal` (`page.tsx:57`, sent at `:98`; backend accepts only `deal`). This is the
product's headline question ("is my journal covered by a deal?") as a dead control.
Fix: use `deal` as the key (or map `deal_coverage` → `deal` in the update function).

**A3. Facet counts ignore the active deal and topic filters. [live]**
With `deal=covered` active (total 10,934), the response reports `oa.true = 69,341` and
topic counts computed over the whole 138,897 corpus. `facet_counts`
(`search.py:242-300`) builds its subquery without `deal` and `topic`, so every other
facet shows numbers the user cannot reach by clicking. Standard faceted search counts all
*other* facets within the currently active filters, excluding only each facet's own key.
Fix: forward `deal`/`topic` into `facet_counts`, excluding the facet's own key per group.
Related asymmetry **[code]**: the oa/doaj/quartile facets keep their *own* active filter
(`search.py:254-256`), so selecting "OA journal" zeroes its own chip's counterpart
("Not OA 0") instead of showing what you would get by toggling.

**A4. "UT works 2020+" double-counts journals with both stat sources. [live]**
Search row for Water Research: `twente_works = 45`. Detail page: 22 (3+4+4+2+3+5+1 across
2020-2026, all `pure_canon`). `TWENTE_WORKS` (`search.py:37-45`) sums
`institution_works_stats.works_count` across **all sources**; the detail endpoint
(`routers/journals.py:246-261`) correctly picks one source per year. Every year with both
`pure_canon` and `openalex_institution_filter` rows counts twice in the list column, in
the `institution_works` sort key, and in the prominence data behind it. Fix: dedupe per
year with the same pure-first precedence as the detail endpoint, or better, fold the
merged number into the proposed denormalized column (B2).

**A5. A NULL sort value makes the next page empty. [code]**
For `sort=2yr_mean_citedness`, a journal with NULL `twoyr` sorts via `coalesce(...,0)`
but the cursor encodes `None` (`search.py:208-211`); the comparison then becomes NULL and
the keyset predicate filters everything. The user sees "138,897 journals", clicks Next,
gets zero rows. Fix: encode `value if value is not None else 0`, matching the coalesce in
`_order`. Also **[code]**: numeric↔float cursor round-trips can skip boundary rows with
tied values; passing the decimal as a string avoids it.

**A6. Malformed cursors silently reset to page 1. [code]**
`parse_cursor` (`search.py:58-66`) swallows every exception. A corrupted or outdated
cursor yields page 1 with no signal, which looks like a search reset. Fix: 400 from the
router when a provided cursor fails to parse.

**A7. Copy and label bugs on data pages. [live]**
- Detail page metrics render OpenAlex's `i10_index` as "IO index"
  (`frontend/app/journals/[issn_l]/page.tsx`, metrics grid).
- About page shows the deals-table timestamp as the "latest data" stamp for
  openaccess.nl, and CSS `capitalize` mangles source names to "Openalex",
  "Openaccess.nl" (`frontend/app/about/page.tsx:60-70,84,126`) — on the page whose job
  is provenance trust.
- Sort dropdown labels ("UT works", "2yr mean citedness") don't match the column headers
  they sort ("UT works 2020+", "2yr citedness") (`frontend/app/page.tsx:34-35,187,201`).
- Deals page mixes number styles: "more than 2200" vs "over 1.300" (European thousands
  dot in English copy).

**A8. Search rows carry fields the frontend never renders. [code]**
`alternate_titles` and `apc_prices` are fetched into the detail payload but have no
references anywhere in `frontend/`. Either render them (see F5) or stop shipping them.

## B. Performance (measured)

Baseline [live]: `GET /api/v1/journals` (browse-all) ≈ **3.0s**; `?q=water` ≈ 2.0s;
filtered ≈ 1.2s. The home page shows a skeleton for that whole time (measured 2.4s from
typing to results). Statement-level EXPLAIN ANALYZE breakdown for one browse-all request:
total-count 288ms + page 33ms + facet aggregate **1501ms** + topic facet **732ms**.

**B1. No search indexes exist. [live]** `journals` (177,181 rows) has exactly two
indexes: both unique b-trees (PK, openalex_id). Every statement seq-scans the table —
the FTS predicate alone shows "Rows Removed by Filter: 176,940". `pg_trgm` is already
installed (`0004_pure_works.py:19`), just unused for search. Fix (new migration):

```sql
CREATE INDEX ix_journals_search_vector ON journals USING gin (search_vector);
CREATE INDEX ix_journals_search_text_trgm ON journals USING gin (search_text gin_trgm_ops);
CREATE INDEX ix_journals_topics ON journals USING gin (topics jsonb_path_ops);
```

Expected effect after B1+B2 [inference]: search endpoints in the tens of milliseconds.
This is the cheapest large win in the report.

**B2. Per-row correlated subqueries evaluated over the whole filtered set. [live]**
`DEAL_COVERED`, `TWENTE_WORKS`, `LATEST_QUARTILE` (`search.py:25-53`) execute as subplans
per row: the EXPLAIN shows `loops=138897` nested-loop nodes, and the facet aggregate that
computes them for all rows is the 1.5s statement. The quartile filter evaluates
`LATEST_QUARTILE` a second time in WHERE (`search.py:154-155`). Fix: denormalize at
ingest — `home_works_count` (merged-source value from A4) and `latest_quartile` as
columns, maintained by the existing `harvest_stats`/`ingest_scimagojr` jobs, plus one
materialized `deal_covered_home` flag or a shared lateral join. This also deletes the
`twente_works`/`quartile` subqueries from `quality_bar_clause`.

**B3. The same filter set is evaluated four times per request. [code+live]**
count, page, facet aggregate, and topic facet each rebuild `base_query`. Fix in two
steps: (1) take the total from the facet aggregate's `count()` (identical predicate when
`deal == "any"`; dedicated count only for covered/not_covered); (2) share one CTE across
facets, or cache facet counts per (query, filters) with a short TTL. The topic facet
additionally explodes `jsonb_array_elements` over all matched rows (measured 684,113
rows) to produce 15 chips; a `journal_topics` junction table refreshed at ingest removes
that cost entirely.

**B4. No HTTP caching anywhere. [code]** Only CORS middleware is installed
(`main.py:33-41`); no gzip, no ETag, no Cache-Control. Meta endpoints are near-static;
search responses compress well. Fix: `GZipMiddleware` (minimum_size=1024),
`Cache-Control: max-age=300` on search, `max-age=3600` on `/meta/*`, ETag on freshness.

**B5. Connection pool at defaults, with a per-request pre-ping. [code]**
`db.py:20`: pool_size 5 + overflow 10; four heavy statements per search means ~10
concurrent users queue while Postgres idles. `pool_pre_ping` adds a round trip per
checkout. Fix: `pool_size=10, max_overflow=10`, drop pre_ping (healthz already probes).

**B6. `/meta/freshness` runs six sequential queries, two unindexed `max()`. [code]**
`meta.py:56-64`; `max(ApcEvidence.period)` can't use the `(issn_l, period)` index;
`InstitutionWorksStats.updated_at` has no index. Cheap: one query with subselects plus a
covering index, and it's cacheable per B4.

**B7. Ingest makes ~1.25M sequential round trips per OpenAlex sweep. [code]**
`ingest.py:96-105` does a point SELECT per record; `common.py:143-153` upserts
`issn_map` once per ISSN variant (~3/journal). ~250k sources → ~6 minutes of pure
latency. Fix: batch the existence check per page; single-statement VALUES upserts.

**B8. LIKE wildcards are unescaped; no diacritic folding. [code]**
`q` containing `%` or `_` acts as a wildcard (`search.py:113,143`). `search_text` keeps
accented characters verbatim, so "economie" misses "économie" — relevant for an
international corpus. Fix: escape in the ilike arguments; consider `unaccent` for the
search vector and search_text.

**B9. `pool`-adjacent ingest risk: failed harvest runs stick at "running". [code]**
`harvest/common.py:190-198` marks the run failed on the same poisoned session; an
asyncpg error there raises again and the status never commits. Fix: rollback first, then
a fresh transaction to record the failure.

## C. Data handling and pipeline

**C1. One JCT refresh corrupts the curated Emerald register. [code]**
`harvest/jct.py:210-217` upserts `Deal` by `esac_id`. Canonical merged deals carry the
JCT esac_id (set by `reconcile._merge`), so re-running `ingest_jct.py` updates the
canonical row in place: publisher flips to the placeholder "EME" code row, `status`
resets to `current`, provenance is replaced, and the linked sheet's ISSNs — for
`eme2025ukb` that is the Elsevier sheet — get inserted under the Emerald deal (~2,000
false "covered" journals). `jobs/ingest_emerald_contract.py` *says* a JCT re-ingest must
not overwrite manual rows; nothing enforces it. The
`enforce_unique_agreement_data` guard (`reconcile.py:313-427`) catches overlap only
later, if reconcile runs. Fix: in `_store_agreement`, skip publisher/status/provenance/
journal writes when the existing deal with that esac_id is canonical
(`openaccess_nl_url` set). Add a regression test that replays ingest-then-curation order.

**C2. The openaccess.nl scrape clobbers curation state. [code]**
`apply_overrides` is documented as "called by every normalizer AFTER its upsert"
(`ingest.py:6,232`), but the only caller is `jct.py:221`. `_upsert_deal`
(`harvest/openaccess_nl.py:297-345`) replaces `summary`, `cap_numbers`, and `provenance`
 wholesale and resets `needs_curation`/`needs_curation_reason` on every scrape — manual
overrides and reconcile flags (e.g. "verify Twente participation") are lost, and the
override protection in `reconcile.py:85-96` guards a field that was already reset. Fix:
call `apply_overrides` after `_upsert_deal` with an oanl-owned field list; merge
provenance instead of replacing it.

**C3. "Twente-covered" means three different things. [code]**
Search requires a `DealInstitution` link (`search.py:25-34`); journal detail treats any
canonical openaccess.nl deal as covered (`routers/journals.py:160-172`); the deals list
uses verified links only (`routers/deals.py:30-34,52-57`). A consortium deal without
enumerated members is "covered" on its detail page and "not covered" in search, facets,
and the quality bar. Fix: one shared SQL condition (institution links OR canonical
openaccess.nl) used by all three paths.

**C4. The OpenAIRE trigram index does not exist. [code]**
`harvest/openaire.py:179-184` claims the match join uses the GIN trigram index on
`ut_works.norm_title`; `0004_pure_works.py:60` created a btree, which cannot serve `%`.
At ~30k works × tens of thousands of OpenAIRE records this is the code's own "470M-row
nested loop" warning. Fix: create the GIN trgm index before the next match run.

**C5. Scimago ingest creates ghost journals. [code]**
`harvest/scimagojr.py:104-108` inserts `Journal(issn_l, in_scimago=True)` for ISSNs the
OpenAlex sweep hasn't covered — NULL title/type rows that surface under `scope=all` and
pollute counts. Fix: UPDATE only; never insert from Scimago.

**C6. `normalize_issn` skips the check digit. [code]**
`harvest/common.py:18-39` validates shape only. One transcription error in any
third-party ISSN fabricates a passthrough key. The standard mod-11 checksum is ~6 lines
in one place; every harvester benefits.

**C7. JCT `row_issn` keeps only one of print/online. [code]**
`harvest/jct.py:81-83` prefers online and drops print; `backfill_deal_issn_l`
(`issn_backfill.py:18-33`) doesn't fall back either, producing false `needs_curation`
rows. Try both candidates.

**C8. `JB_OPENAIRE_ORG_ID` is silently ignored. [code]**
`harvest/openaire.py:32-45` reads a settings attribute that `config.py` never declares,
so the hardcoded Twente openorgs id always wins. Add the field to Settings and
`.env.example`.

**C9. No retirement of vanished openaccess.nl deals. [code]**
Upsert key is `(publisher_id, duration_text)`; a reformat like "2025 – 2027" creates a
duplicate and the old row stays current forever. Pure got a retirement pass
(`harvest/pure.py:634-645`); openaccess.nl needs the same (flag unseen deals, match by
slug first).

**C10. Misc pipeline defects. [code]**
`--seed-deals-only` crashes on a None client (`jobs/harvest_journals.py:30`); the
institution-alias matcher is dead code while OpenAPC filters unknown spellings silently
(`openapc.py:135-138`); enrichment copies raw OpenAlex `issn_l` without validating
against `journals`, so one FK violation kills the chunk, and it overwrites COAR oa_status
with OpenAlex vocabulary (`enrich.py:90-93`); multi-year Pure runs retire everything
outside their year range (`jobs/harvest_pure.py:36`); Scimago's source_record payload
can't be re-normalized from the landing store.

**C11. Corpus-quality observation, not an ingest bug. [live]**
The quality bar's "active recently" branch admits obvious paper-mill journals with huge
work counts ("Journal of Innovative and Creativity (Joecy)", 10,718 works, not in DOAJ;
4,685 journals under the topic "Education and Islamic Studies"). They dominate
browse-all pages and topic facets. Consider down-weighting `is_in_doaj=false` journals
below a works threshold, or an explicit "less relevant" bucket — this is editorial, so
it needs an owner decision.

**C12. Water Research shows 22 UT works since 2020 — verify against Pure. [live]**
3-5 per year for a flagship journal in UT's portfolio looks low. If `pure_canon` is the
authoritative number, fine; but confirm the Pure harvest window/affiliation matching
before publishing numbers externally. Flagged as a question, not a defect.

## D. UX/UI, copy, accessibility

**D1. The landing view is the weakest first impression available. [live]**
With no query, "Relevance" has nothing to rank, so rows come back in ISSN tiebreak
order: page one is obscure zero-data journals ("Technium Books", 0 works, blank
quartile, 0.0). The sort exists that fixes this — default browse-all to
`institution_works` (or citedness), keep relevance for typed queries. Pair with B1 so
the change is instant.

**D2. Filter/sort changes fetch with a stale cursor. [code]**
The cursor reset runs in a `useEffect` after the query already rebuilt with the old
cursor (`frontend/app/page.tsx:67-71` vs `:96-106`): every filter click flashes a wrong
page or an empty state before the corrected refetch. Reset cursor/stack synchronously
inside `update()`.

**D3. "Showing 0–-1 of 0 journals". [code]**
The results footer renders outside the empty/loading conditionals and computes
`pageStart + rows.length - 1` (`page.tsx:447-452`). Render it only when `rows.length > 0`.

**D4. Provenance tooltips are mouse-unreachable. [code]**
`source-note.tsx:40` sets `pointer-events-none` and hover-only visibility with a 6px
gap; the "More info" and source links can't be clicked. Remove the class and bridge the
gap; keep focus support.

**D5. Accessibility and polish. [code]**
Brand orange `#f06e00` on white is 3.03:1 — fails AA at the `text-xs`/`text-sm` sizes it
is used at for links across all pages; add a `--primary-text` token (~`#c25700`) for
text, keep orange for fills. No page sets a document title (the layout defines a title
template nothing uses). Header nav and logo are `<a href>`, so every navigation is a
full document reload that drops React Query cache and scroll restoration — swap to
`next/link`. Quartile chips with count 0 stay clickable and guarantee an empty state.
The `aria-live` counter announces on every debounced keystroke. Metrics grid is fixed
`grid-cols-3` with no breakpoint. The detail chart labels a per-year mix of Pure and
OpenAlex bars as one "Pure registrations" series. The `dark` variant is declared with no
token block — implement it or delete the declaration.

**D6. Error copy exposes internals. [code]**
`lib/api.ts:50` throws `API 500 on /journals` and every error UI prints it verbatim.
Map statuses to human messages (404: "No journal with that ISSN"; 5xx: "Search is
temporarily unavailable") and log details to the console.

**D7. What already works well — do not regress these. [live+code]**
Keyset pagination with deterministic tiebreak; URL-as-state search with debounce and
shareable links; per-statistic provenance notes resolved from a real limitations
registry; skeleton loading with `keepPreviousData`; clear error state with Retry
(observed working); the deals register with contract links; the detail page's
deal-conditions card, metrics, APC evidence table, and OA split (verified against the
API); mobile layout has no horizontal overflow; zero console errors.

## E. Stack, deployment, tests

**E1. Lint never runs. [code]** `frontend/package.json:13` declares `next lint` with no
ESLint dependency or config, and CI only builds. Add `eslint`+`eslint-config-next` and a
CI lint step, or delete the script.

**E2. CI never builds the images it deploys. [code]** Both Dockerfiles are untested
until deploy. Add `docker build` steps.

**E3. `.env` can leak into images. [code]** Neither `.dockerignore` excludes `.env`;
backend `COPY . .` would bake it in. Add `.env*` to both dockerignores.

**E4. Silent test skips. [code]** `tests/conftest.py:15-24` skips DB tests when
`localhost:5433` isn't reachable, so ~30-45% of the suite can vanish green. `JB_TEST_DB`
is checked for truthiness but never used as the URL. Fix: use the variable, report skip
counts loudly (`-rs`), and fail the CI job if the service container never came up.

**E5. Compose hardening. [code]** Postgres published on `0.0.0.0:5433` with a hardcoded
trivial password (also duplicated in 4 places); backend runs as root and migrates on
every boot unconditionally (racy across replicas); no healthcheck/restart policy for
backend or frontend; frontend `depends_on` is start-order only. Minimal: bind
`127.0.0.1:`, `restart: unless-stopped`, healthcheck on `/api/v1/healthz`, non-root
USER, and derive conftest credentials from one place.

**E6. Frontend image ships dev dependencies. [code]** `npm ci || npm install` masks
lockfile drift; the final stage copies the dev-filled `node_modules`. Drop the
fallback; use `output: "standalone"` or `npm prune --omit=dev`.

**E7. Migration reversibility untested. [code]** CI upgrades but never downgrades; one
`downgrade base && upgrade head` step keeps the seven migrations honest.

**E8. Misc. [code]** `API_PROXY_URL` is baked at build time (fine for one environment;
document it); `test_health.py` accepts 500/exception as pass; Actions not SHA-pinned;
the frontend needs no `lint`-less excuse — everything else about the backend Dockerfile
layering is textbook.

## F. Feature ideas (ranked; only after A/B fixes)

1. **Typo-tolerant search**: `word_similarity(q, search_text) > 0.3` OR'd into the
   search predicate; the trigram index from B1 makes it free. Biggest quality-of-life
   win for a search tool aimed at researchers typing imperfect titles.
2. **ISSN input normalization**: strip hyphens/spaces before the exact-ISSN branch
   (`search.py:140-142`) so `00431354` and `0043-1354` both hit. One line.
3. **Export**: CSV of the current filtered result set; BibTeX/RIS-ish "cite this
   journal" block; copy-ISSN button on detail. Cheap, high researcher value.
4. **APC on list cards**: the data is already in `JournalApcAggregate`; show "APC ~€3.5k"
   or "no APC (deal)" on rows and add a "APC ≤ €2k" filter.
5. **Render `alternate_titles`** (already fetched, A8) as "also known as" on detail.
6. **Publisher facet**: `publisher_name` exists on rows; a top-20 publisher facet is a
   familiar axis from the old tool.
7. **"Similar journals"**: shared-topics scoring on detail — useful for "where else can
   I publish?".
8. **Keyboard**: `/` focuses search; Enter submits immediately (skip debounce wait).

## Suggested order of attack

1. **Wave 1 — stop the bleeding (half a day):** A1 (one line), A2, A3, A4, A5, D1
   (sort default), D2/D3. All small, all user-visible.
2. **Wave 2 — performance (a day plus a harvest):** B1 indexes, B2 denormalize +
   backfill, B3 count/facet merge, B4 caching. Then re-run the timing probe from this
   report and expect 2-3s → tens of ms.
3. **Wave 3 — pipeline safety (before the next full refresh):** C1, C2, C3, C4, C5,
   plus regression tests that replay ingest-then-curation order.
4. **Wave 4 — hygiene:** E1-E7, D4-D6, C6-C10, then F features.
