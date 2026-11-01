# Cleanup opportunities

The issues register in `docs/data-pipeline/OVERVIEW.md` (dated
2026-10-29) lists several cleanup candidates. Every item below was
re-verified against the current code and the live database on 2026-10-31;
items that turned out to be fixed are recorded as such instead of being
quietly dropped.

## Postgres statistics never gathered

Still open. No code path in `backend/` runs `ANALYZE` (verified by grep;
nothing in `backend/jobs/`, `backend/alembic/`, or the app does it). In the
live database, 31 of 35 tracked tables have never been analyzed as of
2026-10-31; only `author_works`, `author_identities`, `authors`, and
`pure_person_orgs` were auto-analyzed, and the big fact tables are still
un-estimated. The register's planner example (279,677 estimated vs 177,181
actual journals) dates from this state. Action: run `ANALYZE` after bulk
loads, or tune autovacuum so it triggers on these tables. This needs the
owner, since the live `journalbrowser` database is read-only for agents
(OVERVIEW.md issue 4).

## Sparse observed OA colors

Still open and parked by the owner. `journals.oa_status_observed` is set on
9,148 of 177,181 journals, identical to the 2026-10-29 measurement and
re-checked on 2026-10-31; no gold was ever observed. The sampler in
`backend/src/journal_browser/harvest/journal_oa.py` targets only OpenAlex
`is_oa` venues that lack DOAJ or APC evidence, ignores green on purpose,
and fills NULLs only, so the coverage cannot grow on its own. Owner verdict
2026-10-29: no action for now (OVERVIEW.md issue 5). Revisit only if
`oa_type` misclassification shows up in practice.

## Dead trigram matcher

Still open. `match_openaire_titles` in
`backend/src/journal_browser/harvest/openaire.py` (line 186) has no caller
anywhere in `backend/`, jobs or tests included. Its byproduct lives on: the
live database holds exactly the register's 3,671 `work_identity` rows with
`status='candidate'` that no curation UI reads. Decide one of: wire a
curation flow onto the candidates, or delete the matcher and the candidate
rows together (OVERVIEW.md issue 13 and open question 7).

## Verify-gate window mismatch

Still open, structural. `backend/jobs/verify_utmetadata.py` compares a
2020+ slice on both sides (`Work.year >= 2020` against Pure
`publications:year202x` set specs) while the imported ut-metadata corpus
starts at 2010, and the upstream 2025 set lag makes the gate read red: 40,570
active works locally vs 29,499 distinct upstream records, +37.6% as
measured 2026-10-29 (OVERVIEW.md issue 14). Re-measuring requires the
ut-metadata DSN, which dev machines hold untracked in `backend/.env`.
Action: re-run the upstream 2025+ harvest or align the gate windows.

## Gated scaffolds awaiting a verdict

Both scaffolds are complete transports behind default-off flags, and both
need a turn-on-or-delete decision rather than cleanup:

- `backend/src/journal_browser/harvest/journal_citations.py`
  (`JB_ENABLE_JOURNAL_CITATIONS`, default false). Embedding-based similar
  journals shipped instead of it, which is the main argument for deletion.
- `backend/src/journal_browser/harvest/jisc_opf.py` (`JB_ENABLE_JISC`,
  default false). Zero calls ever made; it starts only when an API key
  arrives.

## Fixed since the register

Two register claims no longer hold, verified 2026-10-31:

- **Stuck `running` runs (issue 8).** The live `harvest_runs` table now has
  zero `running` rows (198 `completed`, 18 `failed`); the six stuck rows
  from 2026-10-29 were resolved. Run inspection no longer misleads.
- **`deal_journals.excluded` as dead code (part of issue 13).** The column
  is load-bearing: deal removals in
  `backend/src/journal_browser/routers/admin/deals_admin.py` set it (a
  deletion would be resurrected by the next JCT harvest), read paths filter
  on it (`routers/journals.py`, `routers/deals.py`,
  `harvest/denorm.py`, `services/publishers.py`), and
  `backend/tests/test_admin_deals.py` covers the behavior.

## Not dead code, just unused data

Two issue-13 claims survive as data states, not cleanup targets:

- **`publisher-pattern` source, 0 rows.** The writer is real now:
  `backend/src/journal_browser/harvest/reconcile.py` derives deal coverage
  from publisher-name patterns, migration
  `backend/alembic/versions/0017_deal_journal_source_pattern.py` allows the
  value, and `tests/test_reconcile.py` exercises it. The live register is
  the hand-curated snapshot, so it holds only `jct` (10,233 rows) and
  `manual` (734) rows as of 2026-10-31. The rows appear if the auto-harvest
  pipeline ever runs against this database.
- **`manual_overrides` empty (0 rows).** The mechanism is live: every
  accepted admin deal edit writes one override row so re-harvests cannot
  undo it. Emptiness only means no admin edit has been made through the
  panel yet.

If the auto-harvest path stays permanently dormant, the publisher-pattern
derivation becomes deletable; until then it is exercised code waiting for
its first live run. The register and its context live in
[Data pipeline](systems/data-pipeline/index.md), the curation flow in
[Admin panel](features/admin.md), and the table shapes in
[Data model](systems/data-model.md).
