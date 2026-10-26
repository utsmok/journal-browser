# Implementation prompt: multi-institute shared-core restructure

Paste this prompt verbatim into a fresh agent session in the repo root
(`/home/sam/dev/journal-browser`).

```text
# Task: restructure journal-browser into a multi-institute shared-core service

Read `docs/multi-institute.md` first — it is the agreed plan (goals, target
design, footguns, implementation order). Implement it fully. Where this prompt
and that document disagree, this prompt wins; post both in your report.

## Goal

One deployment serves multiple universities (University of Twente + University
of Groningen first, any Dutch university later) at per-institution paths
(`/ut/...`, `/rug/...`) with a landing page listing institutions. Everything
institution-neutral is shared in one database: journal universe, single shared
`deals` register, OpenAPC, Scimago, embeddings, global harvest files.
Per-institution: works corpora, stats, Pure/OpenAIRE/enrich harvests,
participation, display config, data windows. Even if only one institution is
ever hosted, the global layer must stay cleanly exportable as a bootstrap
backbone for other instances (global tables carry no institution columns).

## Non-negotiable constraints

1. ONE coordinated cutover, no deferrals, no compatibility shims: the API
   shape change (`twente_works`→`works`, `has_ut_works`→`has_works`,
   `twente_metrics`→`institution_metrics`, similar-cut `"twente"`→
   `"institution"`) lands together with the path-prefix routes
   (`/api/v1/{code}/...` for scoped routes). Old paths and old field names
   die in the same change. No aliases, no deprecation window.
2. Phased commits in the plan's order (schema → harvest split → backend
   serving → frontend → Groningen import → verification/docs), suite green
   and a smoke run after each phase.
3. Never regress search performance: indexes on works/stats/flags lead with
   institution_id; re-check query plans for the two-institution case
   (browse-all, one facet query, one detail page).
4. `docker compose up` on a fresh empty DB must still reach a working
   single-institution site with zero manual steps beyond `.env`.
5. Do not redeploy or restart the live UT stack (docker-compose.yml project
   `journal-browser`). You may freely rebuild/reuse the Groningen stack
   (`jb-groningen`, compose.groningen.yml, DB on port 5543) as a fixture,
   including dropping its volumes. Run test stacks on free ports.
6. Migrations must be reversible on a test DB (`alembic downgrade` path
   works) — the live UT database will be migrated by the user after review,
   so include the exact upgrade sequence in your final report.
7. Follow the repo's rules: uv in `backend/`, npm in `frontend/`, builtins
   over shell for file ops, read before edit, suite must stay green.

## Key facts (verified, trust these)

- Coupling today: `is_home` 12 refs (models, harvest/{common,reconcile,denorm,
  openalex_journals,jct}, routers/journals); `ut_works`/`UtWork` 11 files;
  `journals.deal_covered_home` in models/services/search/harvest/denorm/
  routers. `deal_institutions` + `institutions` tables already exist and are
  populated.
- Display config already flows from `/api/v1/meta/freshness` through
  `frontend/src/hooks/use-site-meta.ts` — extend, don't duplicate.
- Embeddings are institution-neutral (jobs/embed_journals.py: title + topics
  + top-cited OpenAlex works per journal). Keep them global; the
  "institution publishes here" similar-journals cut is per-institution at
  QUERY time.
- Groningen fixture DB (port 5543): 22 deals incl. the LWW case (a deal
  listed at RUG but not UT — ESAC page text differs per uni), 2025-only data
  window, 11,315 Pure works. Use it to validate per-institution scoping and
  participation semantics.
- Test command: `cd backend && uv run pytest` (137 passed / 1 skipped on
  main at task start). Frontend: `cd frontend && npm run build`; API types
  regenerate from `app.openapi()` via `npx openapi-typescript`.
- Purge semantics must invert: today `purge_non_twente_deals` deletes
  non-partner deals. In the shared register, non-participation is a missing
  `deal_institutions` row; shared deals are never deleted. Move per-row purge
  markers off `deal_journals` global state onto the relation.

## Deliverables

1. Alembic migrations (reversible) + backfill: institutions config table
   (seeded from env for the default institution), works/stats renames +
   institution_id, per-institution coverage flags table replacing
   `journals.deal_covered_home`, deal_institutions per-relation fields
   (participation status, `journal_override`), `deal_journals.institution_id`
   for override lists, harvest_state/runs institution scope.
2. Harvest split: global layer once (journals, openaccess.nl, JCT, deal
   reconcile, OpenAPC, Scimago, ISSN-L, embeddings), per-institution layer
   looped (pure, enrich, openaire, stats, participation reconcile, flags).
   Bootstrap DAG becomes two layers; `--from` gains `--institution`.
   Per-institution landing subdirectories.
3. Backend: `/api/v1/{code}/...` scoped routes, top-level `/institutions`
   and `/admin`, per-institution meta/freshness and deals register, the API
   field renames above, regenerated frontend api-types.
4. Frontend: `app/[inst]/...` segment wrapping all existing pages, landing
   chooser at `/` (redirect when one institution), scoped hooks and links,
   admin institution switcher + run list column.
5. Groningen onboarded as an institutions row + per-institution harvest;
   retire compose.groningen.yml (delete it and its README references).
6. Multi-institution tests: institution factory in conftest, scoped search,
   participation differences (LWW case as regression), per-inst windows,
   coverage override list, API shape.
7. Docs updated in the same change: README quick start, DEPLOYMENT.md
   (onboarding a university = one INSERT + one harvest run; env changes),
   and a short backbone-export section (stable list of global tables).

## Verification bar (do all, report evidence)

- `cd backend && uv run pytest` green including new multi-institution tests.
- Fresh-DB compose run on a free port: site up, landing lists the seeded
  institution, search + detail + deals pages work in the browser.
- Two-institution run (default from env + Groningen): both paths serve
  correct scoped data — Groningen 2025-only window visible, the LWW deal
  appears in RUG's register but not UT's, coverage override honored.
- Frontend `npm run build` clean; api-types regenerated from new OpenAPI.
- Search perf spot-check on the two-institution DB: browse-all and one facet
  query not slower than today's live numbers (browse-all ≈ sub-second).
- `alembic upgrade head` + `downgrade base` proven on a throwaway DB.

## Report format

Phases as commits (hash + one line each), verification evidence per the bar,
the exact live-migration sequence for the user to run, deviations from
docs/multi-institute.md with reasons, and a gaps/missed-opportunities
section.
```
