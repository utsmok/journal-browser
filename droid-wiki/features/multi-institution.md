# Multi-institution core

Active contributors: utsmok

## Purpose

One deployment hosts several universities at `/{code}` paths (`/ut`,
`/rug`, and so on) over a shared data core. The journal universe, the NL
deal register, OpenAPC prices, Scimago metrics, and journal embeddings are
harvested once and serve every institution. Each hosted institution adds
its own works corpus, statistics, deal participation, and display
configuration. The rationale for the shared-core design is recorded in
[Design decisions](../background/design-decisions.md).

![The landing page lists every hosted institution](images/web-universities.png)

![Per-institution settings in the admin panel](images/web-admin-settings.png)

## Key abstractions

| Abstraction | Where | Role |
|---|---|---|
| Institution row | `backend/src/journal_browser/models/reference.py` (`Institution`, table `institutions`) | Configuration carrier: path code, name, ROR, harvest sources, data window, display URLs, `active` flag |
| Scope dependency | `backend/src/journal_browser/deps.py` (`get_scoped_institution`) | Resolves the `/{code}` path prefix to an active institution row; unknown or inactive codes 404 |
| Env seed | `backend/src/journal_browser/harvest/common.py` (`ensure_home_institution`) | Seeds the default institution row from `JB_*` env vars on first boot |
| Per-institution flags | `backend/src/journal_browser/models/journals.py` (`JournalFlags`, table `journal_flags`) | One row per journal per hosted institution: works counts, coverage, browse exclusion |
| Deal participation | `backend/src/journal_browser/models/deals.py` (`DealInstitution`, table `deal_institutions`) | Which institutions take part in a shared deal; `journal_override` switches to a per-institution journal list |
| Institution directory | `backend/src/journal_browser/routers/institutions.py` | Public `GET /api/v1/institutions` list that drives the landing page |

## How it works

### Institution row lifecycle

The `institutions` table lists every openaccess.nl deal participant, because
the JCT/ESAC ingest creates an inactive, code-less row for each institution
named in a deal sheet. Only rows with a `code` and `active = true` are
hosted.

On first boot, `ensure_home_institution` in
`backend/src/journal_browser/harvest/common.py` seeds the default row from
the env levers in `backend/src/journal_browser/config.py`
(`JB_INSTITUTION_CODE`, `JB_INSTITUTION_NAME`, `JB_INSTITUTION_SHORT`,
`JB_INSTITUTION_ROR`, plus display and source variables). If the configured
ROR already matches a participation-only row, the seed fills that row in
rather than inserting a duplicate. From then on the table is authoritative:
later env changes never update an existing row, which
`DEPLOYMENT.md` documents under "Adding a second institution". The
env-seeded home institution is identified by its ROR, not by a flag.

### Global vs per-institution settings

`backend/src/journal_browser/settings_schema.py` tags every editable knob
with a `section`. Global values live in the `settings.yaml` overlay and are
edited through `PUT /api/v1/admin/settings`; institution-section values are
columns on the institutions row and are edited through
`PUT /api/v1/admin/institutions/{code}`. The settings endpoint rejects
institution-section keys with a 400 that points at the institutions
endpoint, so the two scopes cannot be mixed. The settings-system internals
are covered in [Backend configuration](../apps/backend/configuration.md),
and the admin side in [Admin panel](admin.md).

### Shared and per-institution tables

The split is deliberate: global tables carry no institution columns, so a
backbone `pg_dump` of them stays a stable table list (see `DEPLOYMENT.md`,
"Backbone export").

| Scope | Tables |
|---|---|
| Shared | `journals`, `issn_map`, `publishers`, `deals`, shared `deal_journals` rows (`institution_id IS NULL`), APC evidence and OpenAPC, Scimago metrics, JCT, the `journals.embedding` column, `works_metadata_cache` |
| Per institution | `works` (`institution_id` is part of the primary key), `work_identity`, `institution_works_stats`, `institution_trends`, `journal_flags`, `deal_institutions`, institution-scoped `deal_journals` rows, `author_identities` and the author tables |
| Nullable scope | `harvest_runs` and `harvest_state` carry a nullable `institution_id`; NULL means a global job |

The institution and feedback application tables live in
`backend/src/journal_browser/models/app_data.py`; institution rows and the
deals core live in `backend/src/journal_browser/models/reference.py`. Both
are described on [Data model](../systems/data-model.md).

### The /{code} route contract

In `backend/src/journal_browser/main.py`, the global routers
(`institutions`, `admin`, `feedback`, `docs`) register before the scoped
router `/{institution_code}`, so `/api/v1/admin/deals` is never captured as
institution `admin`. The scoped router mounts `journals`, `authors`,
`publishers`, `orgunits`, `deals`, and `meta`.

`get_scoped_institution` in `backend/src/journal_browser/deps.py` looks up
the path code among active institutions and raises 404 for anything else;
`backend/tests/test_multi_institution.py` pins that behavior
(`test_unknown_institution_404s`). Field names are institution-neutral
after the coordinated cutover: `works`, `has_works`, `institution_metrics`,
and the `institution` facet in similar-journal listings (formerly the
`twente_*` names). Search results, facets, deal lists, and freshness
windows are all scoped to the resolved row:

- Works counts and the `has_works` filter read `journal_flags` for the
  scoped institution (`test_search_scopes_works_and_has_works`).
- The deals listing follows `deal_institutions` participation.
  Non-participation is a missing relation row, never a deletion of the
  shared register; the LWW agreement listed for Groningen but not Twente is
  the regression case (`test_lww_deal_participation_difference`).
- Effective coverage uses the institution's own journal list when the
  relation has `journal_override` set, otherwise the shared list
  (`test_coverage_override_list`).
- Data windows come from the row: Groningen runs 2025-only while Twente is
  open-ended (`test_per_institution_windows_in_freshness`).

### Landing redirect behavior

`frontend/app/page.tsx` fetches `GET /api/v1/institutions`, which returns
only hosted (active, coded) institutions with their data windows:

- One result: the page immediately calls `router.replace("/{code}")`, so a
  single-institution deployment never shows a chooser.
- Several results: the page renders one card per institution and links to
  `/{code}`.
- Backend unreachable: the page renders an error card instead.

`frontend/app/[inst]/layout.tsx` wraps every per-institution page in
`InstitutionProvider`, and `frontend/hooks/use-institution.tsx` exposes the
code through `useInstitution()`. The context is the empty string on global
surfaces (the landing chooser and the admin panel), which tells data hooks
whether to prefix their requests.

### Onboarding a second university

Per `DEPLOYMENT.md`, onboarding is one SQL statement plus one harvest run,
with no second stack and no extra ports:

1. Claim the existing inactive row with one `UPDATE institutions SET ...`
   statement: set `code`, `short_name`, `active`, `ror`,
   `pure_oai_base_url`, `openaire_org_id`, the data window, and the display
   URLs.
2. Run the per-institution harvest layer only:
   `docker compose run --rm bootstrap sh -c "uv run --no-dev python jobs/bootstrap.py --institution rug"`.

`openaire_org_id` is required and cannot be derived from the ROR
(`backend/src/journal_browser/config.py`). The landing page picks the new
institution up automatically because it reads the same directory endpoint.

### Name matching in harvest sources

`backend/src/journal_browser/harvest/institution_aliases.py` is a seeded
alias map for the home institution's name spellings ("University of
Twente", "Universiteit Twente", "UT", ...). `match_institution` returns the
canonical name plus the variant that matched; unknown names go through
`log_unknown_institution` and are logged for review, never dropped
silently. `backend/tests/test_institution_aliases.py` covers the mapping.

## Integration points

- Per-institution harvest jobs resolve their target through
  `resolve_institution` in
  `backend/src/journal_browser/harvest/common.py`, which maps the
  `--institution` flag to a row and falls back to the env-seeded home. See
  [Data pipeline](../systems/data-pipeline/index.md).
- Author search respects each row's `require_confirmed_affiliation` flag:
  only authors whose Pure affiliation resolves to the institution's ROR are
  listed, while profiles stay accessible.
- The admin panel edits institution rows and reads per-institution run
  history; see [Admin panel](admin.md).

## Entry points for modification

- Host another university: the SQL UPDATE plus targeted bootstrap run above.
  This is an operator task, not a code change.
- Add a per-institution configuration knob: add the column to `Institution`
  in `backend/src/journal_browser/models/reference.py`, extend
  `InstitutionUpdate` and `_institution_payload` in
  `backend/src/journal_browser/routers/admin/settings_admin.py`, and add a
  `section="institution"` field in
  `backend/src/journal_browser/settings_schema.py`. Then regenerate
  `frontend/lib/api-types.ts` from the refreshed `openapi.json`.
- Add a per-institution harvest job: resolve the row with
  `resolve_institution`, record the run with `institution_id` set, and wire
  the job into the DAG layer in `backend/jobs/bootstrap.py`.
- Change scope resolution: `backend/src/journal_browser/deps.py` and the
  registration order in `backend/src/journal_browser/main.py`.

## Key source files

| File | Contents |
|---|---|
| `backend/src/journal_browser/models/reference.py` | `Institution` model and the deals tables |
| `backend/src/journal_browser/deps.py` | `InstitutionDep` scope resolution |
| `backend/src/journal_browser/harvest/common.py` | Env seed, active-institution lookup, `--institution` resolution |
| `backend/src/journal_browser/routers/institutions.py` | `GET /api/v1/institutions` directory |
| `backend/src/journal_browser/routers/admin/settings_admin.py` | `GET/PUT /admin/institutions/{code}` |
| `backend/src/journal_browser/harvest/institution_aliases.py` | Home-institution alias map |
| `backend/src/journal_browser/config.py` | `JB_INSTITUTION_*` env levers |
| `backend/src/journal_browser/main.py` | Router registration order |
| `backend/tests/test_multi_institution.py` | Scoping, participation, override, and window regressions |
| `backend/tests/test_institution_aliases.py` | Alias-matching unit tests |
| `frontend/app/page.tsx` | Landing chooser and solo redirect |
| `frontend/app/[inst]/layout.tsx` | `InstitutionProvider` wrapper |
| `frontend/hooks/use-institution.tsx` | `useInstitution()` scope hook |
