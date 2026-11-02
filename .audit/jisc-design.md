# JISC Open Policy Finder — full integration design (2026-11-02)

Owner-approved goal: sweep ALL JISC OPF data into the stack (raw + normalized),
canon-link entities, enrich journals, expose in API + frontend, then compare
against existing data for gaps/deal improvements.

## Definition of done (predicate)

1. All 6 item types swept: `source_records` count per type == live `object_ids` total.
2. ≥99% of serving-scope journals (`works_2020_plus > 3`) carry `jisc_harvested_at`.
3. Migration(s) upgrade+downgrade cleanly on a throwaway DB.
4. Journal detail exposes `green_oa`; search supports `green_oa` param + facet;
   `openapi.json` + `lib/api-types.ts` regenerated together (CI drift check green).
5. Journal page shows the policy card; facet chip works — verified in a real browser.
6. Backend pytest green, ruff/ty green, frontend lint + build green.
7. Comparison analysis doc landed with measured numbers.

## Verified API contract (live 2026-11-02)

- Base `https://api.openpolicyfinder.jisc.ac.uk`; `x-api-key` header; query params
  `item-type` (REQUIRED) + `format=Json` (REQUIRED) + `limit` (≤? see below) + `offset`
  (`object_ids`: offset < 10000) + `search_after` (echo back the returned
  `next_search_after` value, a JSON-array string like `"[6]"`).
- `/retrieve` list → `{"items": [...], "totalHits": <capped at 10000>, "next_search_after": [6]|null}`.
- `/retrieve_by_id?identifier=<issn|sherpa id|slug>` → `{"items": [record]}`; miss = 200
  with empty `items`. Accepts ANY ISSN of a journal (print or electronic).
- `/object_ids?item-type=X&limit&offset` → CSV `id,date_modified` per line; limit max
  observed working 5000; offset must be < 10000 (use search_after beyond? not verified
  for object_ids — for sweeps use /retrieve with search_after instead).
- `filter` param: valid JSON array of `[field,operator,value]`, e.g. `[["issn","equals","0043-1354"]]`.
- Item types + measured corpus: publication ≥10000 (totalHits capped; count at sweep),
  publisher_policy 3875, publisher 3484, repository 6239, funder 202, funder_group ~1059+.
- Pacing: no rate-limit headers seen; 0.1–0.15s sleep between calls is safe. Limit=100 fine.

### Record shapes (phrases: every discrete field has a `*_phrases` sibling — strip them at normalize; raw keeps everything)

- **publication**: `id`, `type` ("journal"), `title: [{title, language}]`,
  `url`, `issns: [{type: print|electronic, issn}]`, `listed_in_doaj: yes|no`,
  `publishers: [{relationship_type, publisher: {id, name, url, country, ror? in identifiers,
  publication_count, imprints_id?}}]`, `publisher_policy: [{id, open_access_prohibited,
  internal_moniker, urls: [{url, description}], permitted_oa: [...], publication_count}]`,
  `system_metadata {id, date_created, date_modified, uri, publicly_visible}`.
- **permitted_oa entry**: `id`, `article_version: ["submitted"|"accepted"|"published"]`,
  `license: [{license: cc_by|cc_by_nc|..., version?}]`, `additional_oa_fee: yes|no`,
  `conditions: [str]`, `copyright_owner?`,
  `location: {location: [any_website|this_journal|authors_homepage|institutional_repository|
  named_repository|subject_repository|non_commercial_website|non_commercial_repository|
  any_repository], named_repository: ["arXiv", ...]?, embargo?: [...]}` (embargo key absent
  in all sampled records — treat as optional, store months when `amount_units`+`units` found),
  `publisher_deposit?: [repository objects]` (embeds OpenDOAR records: system_metadata.uri
  `https://opendoar.ac.uk/repository/<id>`).
- **publisher_policy**: `id`, `internal_moniker`, `open_access_prohibited`, `urls`,
  `permitted_oa`, `publication_count`, `publications: [...]`, `publisher: {...}`,
  `workflow_dates: {policy_last_reviewed: "2026-02-06"}`.
- **publisher**: `id`, `name`, `url`, `country` (ISO-2), `identifiers: [{type: ror, identifier}]`,
  `imprints: [{id, name, ..., imprint_of_id}]`, `publication_count`, `publications?`.
- **funder**: `id`, `funder_metadata {name, url, country, identifiers}`,
  `open_access_data_archiving_policy {requirement, what, special_conditions, urls}`,
  `open_access_publications_policy {archiving_policy, publishing_policy, notes, urls,
  policy_effective_date}`.
- **funder_group**: `id`, `funders: [{id, name, type, uri}]` (name key may be absent → null).
- **repository** (OpenDOAR): `id` (OpenDOAR id), `repository_metadata {name, type,
  url, oai_url, software, content_subjects, content_types, full_text_record_count,
  metadata_record_count}`, uri `https://opendoar.ac.uk/repository/<id>`.

### THE critical matching rule

Match journals by the REAL ISSNs in `journals.issns` (jsonb string array) — NEVER by
`issn_l` alone (ISSN-L ≈19% hit rate vs 100% via `issns`). Reuse the DOAJ matcher shape:
`Journal.issn_l.in_(chunk) | Journal.issns.op("?|")(bindparam(..., type_=ARRAY(Text)))`,
chunked ≤20,000 binds.

## Schema (migration 0031 `0031_jisc_policy`, models in `models/jisc.py`)

All tables: plain int PK = Sherpa/OpenDOAR id; `date_modified timestamptz null`;
`harvested_at timestamptz not null default now()`; no FK constraints (harvest order
independence); CheckConstraint only where a status enum exists (none here).

- `jisc_publications`: id PK, title text null, pub_type text null, url text null,
  listed_in_doaj bool null, issns jsonb (list of {type, issn}), publisher_ids jsonb
  (list of ints), policy_ids jsonb (list of ints), issn_l varchar(9) null (resolved
  via journals.issns / IssnMap at normalize time).
- `jisc_publishers`: id PK, name text, url text null, country varchar(2) null,
  ror text null, publication_count int null, imprint_of_id int null.
- `jisc_policies`: id PK, publisher_id int null, open_access_prohibited bool null,
  internal_moniker text null, urls jsonb null, workflow_dates jsonb null,
  permitted_oa jsonb null, publication_count int null.
- `jisc_funders`: id PK, name text null, country varchar(2) null, url text null,
  identifiers jsonb null, publications_policy jsonb null, data_archiving_policy jsonb null.
- `jisc_funder_groups`: id PK, name text null, funders jsonb null.
- `jisc_repositories`: id PK (OpenDOAR id), name text null, type text null, url text
  null, oai_url text null, software text null, content_subjects jsonb null,
  content_types jsonb null, full_text_record_count int null, metadata_record_count int null.

`journals` new columns (all nullable, DOAJ tri-state convention — NULL = never swept):

- `jisc_in_opf bool`, `jisc_oa_prohibited bool`, `jisc_sherpa_id int`,
- `jisc_allows_sa_submitted bool`, `jisc_allows_sa_accepted bool`, `jisc_allows_sa_published bool`,
- `jisc_embargo_accepted_months int`,
- `jisc_policy jsonb` (display object, shape below), `jisc_harvested_at timestamptz`.

`journals.jisc_policy` display object (built by normalizer, phrases stripped):

```json
{
  "routes": {
    "submitted":  {"locations": [...], "repositories": [...], "licenses": [...],
                   "embargo_months": null, "conditions": [...], "additional_oa_fee": "no"},
    "accepted":   {...}, "published": {...}
  },
  "open_access_prohibited": false,
  "internal_moniker": "...",
  "urls": [{"url": "...", "description": "..."}],
  "policy_uri": "https://openpolicyfinder.jisc.ac.uk/publication/<sherpa id>"
}
```

Aggregation rule: across all publisher_policy[].permitted_oa entries, group by
article_version; union locations/licenses/conditions/repositories; embargo_months = min
of stated embargo amounts for that version (null when none stated anywhere);
`open_access_prohibited` = true if ANY policy prohibits.

Migration 0032 `0032_jisc_limitations` seeds (INSERT … ON CONFLICT (code) DO NOTHING;
downgrade deletes):

- `jisc-policy-currency`, source `jisc-opf`, scope `journals.green_oa`, severity `info`,
  hint: "Publisher self-archiving policies are curated by Jisc Open Policy Finder and
  reviewed periodically; always confirm with the publisher before relying on them.",
  url `https://openpolicyfinder.jisc.ac.uk`.
- `jisc-cc-by-nc-nd`, source `jisc-opf`, scope `journals.green_oa`, severity `info`,
  hint: "Policy text is Jisc content under CC BY-NC-ND 4.0: shown verbatim, never
  paraphrased.", url `https://creativecommons.org/licenses/by-nc-nd/4.0/`.

## Harvester (extends `harvest/jisc_opf.py`, job `jobs/harvest_jisc.py`)

- `SWEEP_TYPES = ("publication", "publisher", "publisher_policy", "funder",
  "funder_group", "repository")`.
- `sweep_type(client, ingest, item_type, page_size=100, sleep_s=0.15) -> stats`:
  loop `/retrieve` with `search_after`; each record `ingest_record(str(system_metadata.id), record)`
  (batched via `ingest_records` per page); `await ingest.commit()` per page; stop when
  `next_search_after` null or `items` empty. entity_type = item_type.
- `harvest_all(session, only: str|None = None)` wraps each type in its own
  `run_harvest("jisc_opf", item_type, "all", {"mode": "retrieve-sweep"}, body, session)`
  so each type gets its own HarvestRun/HarvestState row. Idempotent full refresh:
  reruns dedupe on content_hash. Key from `get_settings().jisc_api_key`.
- Job CLI: `uv run python jobs/harvest_jisc.py [--only publication] [--limit-records N]`.
- The old `harvest_policies`/`assert_enabled` gating: superseded — the sweep runs like
  every other manually-triggered job (no flag). Remove `assert_enabled`/`enable_jisc`
  with the flag removal unit; keep module docstring accurate.

## Normalizer (`harvest/jisc_normalize.py`, job `jobs/normalize_jisc.py`)

`normalize_jisc(session)` wrapped in `run_harvest("jisc_opf", "normalized", "all", ...)`:

1. For each entity type: SELECT latest SourceRecord payload per source_pk
   (dedupe by content_hash recency), strip `*_phrases` recursively, extract
   `name` (first English/preferred entry), upsert the tables above.
2. publications: resolve `issn_l` via `IssnMap` + `journals.issns` containment.
3. Journals stamping: build per-publication display object (aggregation rule), then
   bulk UPDATE matching the DOAJ `?|` ISSN matcher over the union of all JISC ISSNs.
   Stamp: `jisc_in_opf=true, jisc_oa_prohibited, jisc_sherpa_id, allows_sa_*,
   embargo_accepted_months, jisc_policy, jisc_harvested_at=now()`.
   Match set = ONLY issns present in jisc_publications.
4. Facet rank (best allowed route): submitted > accepted > published; none = in_opf
   AND no route (or prohibited). `green_oa` query values: submitted/accepted/published/none.
5. oa_type classification is NOT touched: JISC policy existence is not OA-color
   evidence (subscription journals have policy records too).
6. Stats: per-type upserts, journals_matched, embargo_present counts.

## API + facets

- `routers/journals.py` detail: add `green_oa` block built from `journals.jisc_policy`
  (+ null when unswept); `ATTRIBUTION["green_oa"] = {source: "Jisc Open Policy Finder",
  url: "https://openpolicyfinder.jisc.ac.uk", caveat_codes: ["jisc-policy-currency",
  "jisc-cc-by-nc-nd"]}`.
- Search: `green_oa` query param (single value, 422 on junk, same style as `oa`),
  SQL per mapping above; facet bucket `green_oa` with the four values in
  `services/search/facets.py` (follow the drop-own-dimension pattern).
- Schema classes in `schemas.py`; then `uv run python scripts/dump_openapi.py` +
  `cd frontend && npm run generate` (commit together).

## Flag removal (clean cutover)

Delete `enable_jisc` everywhere: `config.py` field, `settings_schema.py` entry,
`docker-compose.yml` env passthrough, root `.env` line, `.env.example`,
`settings.yaml.example`, live `backend/settings.yaml` key (CRITICAL: overlay reloads
live on mtime — stale key must not crash `Settings.model_validate`; verify extra-key
behavior in config.py and add a regression test), droid-wiki mention optional.
Keep `jisc_api_key`. Update `tests/test_scaffolds.py` (drop skip-when-disabled test
or repurpose), `.factory/skills/qa/config.yaml` note, and docs mentions.

## File ownership matrix (disjoint per unit)

- A models+migration: `models/jisc.py`, `models/__init__.py` (export), 2 migration files.
- B harvester: `harvest/jisc_opf.py`, `jobs/harvest_jisc.py`, `tests/test_jisc_opf.py`
  (MOVE the 3 jisc tests out of `tests/test_scaffolds.py` into it; update docstring there).
- F flag removal: `config.py`, `settings_schema.py`, `docker-compose.yml`, `.env.example`,
  `backend/settings.yaml`, `backend/settings.yaml.example`, root `.env`,
  `tests/test_scaffolds.py` (jisc-skip test removal overlaps B's file — F owns ALL of
  test_scaffolds.py edits; B must NOT edit test_scaffolds.py, B creates test_jisc_opf.py
  and F removes the stale skip test), `.factory/skills/qa/config.yaml`.
- C normalizer: `harvest/jisc_normalize.py`, `jobs/normalize_jisc.py`, `tests/test_jisc_normalize.py`.
- D API: `routers/journals.py`, `services/search/*`, `schemas.py`, `tests/test_jisc_api.py`,
  then openapi + api-types regen.
- E frontend: `frontend/*` after D.

## Verification per unit

- A: `alembic upgrade head` + `downgrade -1` + re-`upgrade` on throwaway DB (tests do
  create_all; run alembic against a scratch DB manually, e.g. create db via psql on
  localhost:5433 then drop).
- B: `uv run pytest tests/test_jisc_opf.py -q` (MockTransport; no live calls) +
  `--limit-records 3` live smoke allowed via `--only publisher` (writes to LIVE DB
  source_records — acceptable, dedup idempotent).
- C: `uv run pytest tests/test_jisc_normalize.py -q` (throwaway DB via `db` fixture,
  synthetic SourceRecords).
- D: `uv run pytest tests/test_jisc_api.py -q` + full `pytest -q` if DB free.
- E: `npm run lint && npm run build` + browser visual check (owner does this).

House rules: uv only (never pip/python bare); ruff line 100 (E,W,F,I,UP,B,SIM,C4,RET,RUF);
en-dashes/arrows allowed; pytest asyncio_mode auto; `JB_SETTINGS_YAML` tmp-path trick for
flag tests; never edit `alembic/versions` formatting beyond your own new file; tests use
the `db` fixture (throwaway DB) — the live DB is read-only except through jobs.
