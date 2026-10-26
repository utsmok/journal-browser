# Multi-institute architecture: shared core, per-institution serving

Status: plan (agreed direction, not yet implemented). Owner: implementing agent
per `docs/multi-institute-agent-prompt.md`.

## Goals

1. One deployment serves multiple institutions (first: University of Twente +
   University of Groningen; later: any Dutch university) with per-institution
   paths: `/ut/...`, `/rug/...`, and a landing page listing institutions.
2. Share everything institution-neutral in one database: the journal universe,
   the deal register (single `deals` table), OpenAPC, Scimago, journal
   embeddings, and the global harvest raw files.
3. Keep per-institution: works corpora, stats, Pure/OpenAIRE/enrich harvests,
   reconcile participation, curation scope where needed, display config, data
   windows.
4. Even if we never host a second university on one server, the global/shared
   layer must stay cleanly separable so it can be exported as a bootstrap
   backbone (e.g. a pg_dump of the global tables another instance restores
   before running its own per-institution harvests).
5. One coordinated cutover: the API shape change (institution-specific field
   names) happens in the same change, no compatibility aliases, no deferred
   migrations.

## Current state (measured)

- `deal_institutions` (deal ↔ institution m:n) and a populated `institutions`
  table already exist; `is_home` (12 references across models, harvest, one
  router) marks the single configured institution.
- Works/stats are single-institution: `ut_works`, `work_identity`,
  `institution_works_stats`, `institution_trends` (11 files).
- `journals.deal_covered_home` is a single boolean maintained by
  `harvest/denorm.py`; search/facets/sorts read it plus `twente_works` /
  `has_ut_works` API fields.
- Institution identity + display + sources live in env vars
  (`JB_INSTITUTION_*`, `JB_PURE_OAI_BASE_URL`, `JB_OPENAIRE_ORG_ID`, windows).
- Embeddings are institution-neutral (title + topics + top-cited OpenAlex
  works per journal) — verified; they stay global.
- Bootstrap runs a dependency DAG; `--from` is the serial repair path.
- The frontend reads display config from `/meta/freshness` via `useSiteMeta`
  (single touchpoint), but API field names (`twente_works`, `twente_metrics`,
  similar-journals cut `"twente"`) are baked into types and pages.

## Target design

### Data model

- `institutions` becomes the institution configuration carrier:
  `code` (`ut`, `rug`), name, short name, ROR, OpenAlex id, `pure_oai_base_url`,
  `openaire_org_id`, optional `ut_metadata`-style external DSN, data window
  start/end, display fields (library URL, OA guide URL, support email, admin
  contact, research portal URL), `active` flag, `is_default` for root-path
  redirect. The env vars remain only as the seed for the default institution
  on first boot; after that the table is authoritative.
- Remove `is_home` usage from queries; institution identity comes from the
  request scope.
- `deals` stays a single shared table. `deal_institutions` is the partnership
  relation and gains per-relation fields:
  - participation status/notes (e.g. negotiated locally vs via UNL),
  - `journal_override` flag: when true, that institution's coverage is the
    per-relation list instead of the shared sheet list.
- `deal_journals` gains a nullable `institution_id`: NULL rows are the shared
  coverage from the ESAC/JCT/openaccess.nl sheets; institution-scoped rows are
  overrides. Effective coverage for an institution = override rows if the
  relation has `journal_override`, else the shared NULL rows. (Exact semantics
  may be refined; the invariant is: one deal row, per-institution partnership
  and coverage.)
- Works/stats get `institution_id`: rename `ut_works` → `works` (alembic
  rename, not drop-and-recreate), add the column, backfill from the default
  institution. Same for `work_identity`, `institution_works_stats`,
  `institution_trends`. Composite unique keys gain the column.
- Replace `journals.deal_covered_home` with a per-institution materialized
  flag table (institution_id, issn_l) refreshed by the denorm per institution;
  search stays a simple indexed join. Drop the old column in the same
  migration.
- `harvest_state` / `harvest_runs` get a nullable `institution_id` (NULL =
  global job). Landing zone gets a per-institution subdirectory for
  per-institution raw files (pure, openaire); global files stay at the root.

### Harvest orchestration

- Global layer (once per deployment): journals sweep, openaccess.nl scrape,
  JCT ingest, deal identity reconcile (merging sheets/aliases is
  publisher-level, not institution-level), OpenAPC, Scimago, ISSN-L backfill,
  embeddings.
- Per-institution layer (loop over active institutions): Pure OAI harvest,
  enrich, OpenAIRE, stats, participation reconcile (which deals apply to this
  institution — the LWW lesson: participation text differs per page),
  coverage denorm + flags for that institution.
- Bootstrap DAG becomes two layers; `--from` gains `--institution`.
- `JB_BOOTSTRAP=auto` skip check stays global (journals present).

### Serving / API

- Institution resolution by path prefix: `/api/v1/{code}/...` for scoped
  routes (journals search + detail + works + similar, deals register, meta,
  freshness). Unprefixed `/api/v1/institutions` (public list for the landing
  page) and `/api/v1/admin/*` (global, with an institution query filter) stay
  top-level. Unprefixed scoped routes 404 — clean cutover, no default-institution
  aliasing on the API (the frontend always prefixes; the root page redirects).
- API shape break in the same cutover: `twente_works` → `works`,
  `has_ut_works` → `has_works`, `twente_metrics` → `institution_metrics`,
  similar-journals cut `"twente"` → `"institution"`, sort `institution_works`
  stays but means "selected institution's works". Regenerate
  `frontend/lib/api-types.ts` from the new OpenAPI.
- `/meta/freshness` per institution: display block + harvest state + table
  timestamps scoped to that institution.
- Deals register per institution: deals where the partnership relation exists
  for the scoped institution; journal counts use that institution's effective
  coverage.

### Frontend

- `app/[inst]/...` route segment wrapping search, deals, about, journal
  detail, admin; `app/page.tsx` becomes the institution chooser (server
  component listing active institutions, redirect when only one is active).
- All data hooks take the institution code from the segment; `useSiteMeta`
  becomes `useSiteMeta(inst)`; internal links carry the prefix.
- Admin panel: global login, institution selector, run list with institution
  column, flagged deals shown per selected institution.
- Per-institution metadata (title templates) where cheap.

### Deployment / migration

- Single compose stack; `compose.groningen.yml` is retired after Groningen is
  imported as an institutions row + per-institution harvest (its existing DB
  is the backfill source or it simply re-harvests Pure/OpenAIRE/stats —
  implementer's choice; re-harvest is simpler and validated).
- Existing single-institution deployments: migration synthesizes the default
  institution row from current env/config and stamps existing rows.

## Footguns and things to take into account

1. **Purge semantics invert.** Today `purge_non_twente_deals` deletes deals
   the home institution isn't part of. In a shared register that must never
   delete a shared deal — non-participation is a missing `deal_institutions`
   row, not deletion. Rework the job into participation marking; the existing
   per-row `purged` source marker on `deal_journals` is global state and
   conflicts with per-institution reality — move it to the relation.
2. **Curation is shared, works are not.** `needs_curation` on a deal is global
   (one Elsevier row). A fix one librarian makes applies to all institutions —
   intended, but say so in the admin UI. `ManualOverride` rows may need an
   optional institution scope for works-level fixes.
3. **Data windows are per institution** (Groningen runs 2025-only). Stats,
   browse visibility (>3 works filter), and trend charts must read the scoped
   institution's window, not a global one.
4. **Indexes lead with institution_id** on works/stats/flags tables; the
   search path was performance-tuned once already (177k journals, GIN) — don't
   regress it. Facet queries become institution-scoped; re-check the query
   plans for the two-institution case.
5. **ut-metadata DSN is UT-specific.** It's an optional per-institution
   enrichment source, not global config; other institutions have no
   equivalent.
6. **Similar-journals "institution publishes here" cut is per-institution at
   query time** (filter by that institution's works), never at embed time —
   embeddings stay global.
7. **One cutover, no aliases.** Old unprefixed API paths and old field names
   die in the same change; frontend, generated types, and any saved
   documentation update together. Regenerate `api-types.ts` from OpenAPI.
8. **Backfill ordering:** the institutions row must exist before works rows
   get stamped; run inside one alembic migration with env-derived defaults.
9. **Test fixtures** are single-home today; the conftest needs an institution
   factory and multi-institution cases (scoped search, participation
   differences — LWW is the canonical case: partner at RUG, not at UT).
10. **Landing/report layout:** per-institution subdirectories for per-inst
    sources; the curation report stays global for deals but its participation
    section is per institution.
11. **`docker compose up` on a fresh DB** must still work end-to-end with zero
    manual steps: seed the default institution from env, run global + default
    institution harvests. DEPLOYMENT.md and README quick start get updated in
    the same change (new env vars if any, institutions onboarding section,
    Groningen as a row not a stack).
12. **Export story:** keep global tables free of institution columns so a
    backbone pg_dump is a stable table list; document the list.

## Suggested implementation order

1. Schema + alembic migrations + config table + backfill (+ tests).
2. Harvest jobs split (global vs per-institution), two-layer bootstrap DAG,
   landing subdirs (+ tests).
3. Backend serving: scope resolution, new route shape, per-inst meta/deals,
   API field renames, regenerate types (+ tests).
4. Frontend: `[inst]` segment, chooser landing page, scoped hooks, admin
   switcher (+ build).
5. Groningen import/onboarding; retire `compose.groningen.yml`.
6. Full verification on local stacks; docs updates (README, DEPLOYMENT.md).

Each phase ends with the suite green and a smoke run; the whole change lands
as reviewable commits per phase.
