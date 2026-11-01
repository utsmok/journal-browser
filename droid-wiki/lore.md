# Lore

journal-browser was created on Oct 22, 2026, and by the evening of Nov 1, 2026 it held 270 commits, all from one developer (mostly committed as `utsmok`, five times as Sam or Samuel Mok; the same person). The project rebuilds the WUR-hosted Open Access journal browser as a Twente-first, open-data-only search tool. Ten days is short, but the shape of the code changed several times in that span.

One caveat on sources: `docs/` is mostly gitignored (since Oct 23, 2026, commit `2d65f23`), so this wiki's view of the documentation history rests on the two tracked files, `docs/data-pipeline/OVERVIEW.md` and `docs/multi-institute.md`. The rest of this story is reconstructed from commit timestamps and the dated decision and issues registers those docs reference.

## Eras

### Oct 22, 2026: the whole v1 in one day

The first commit landed at 12:58 (`e4e57a6`): FastAPI, Next.js, and docker skeletons plus research docs and an implementation plan. The morning went to prior art and decisions 1-11, including one correction that still matters: an early draft assumed WUR as the institution, and was fixed to Twente's ROR (`006hf6230`) the same day. The rest of the day built phases 0-7 of `docs/plan.md`: alembic and the harvest core, the openaccess.nl scraper, OpenAPC, the JCT dump with reconcile, the OpenAlex journal-universe sweep (268,874 sources stored, 177,181 normalized journals, a universe still in use today), the search/deals/meta API, a first frontend, live-verified Twente stats, and a passing compose smoke test. The evening brought the first data triage: the Emerald deal was rebuilt from the signed contract (`4ba470b`) after JCT served the wrong publisher's sheet, and decision 13 made openaccess.nl the canonical deal register. 29 commits total.

### Oct 23-24, 2026: owner verdicts, then the embeddings turn

The verdicts came after midnight (the commits are timestamped 00:27-01:21). Decision 14 made the deal register manual and Twente-only: 595 rows purged, 16 kept, and the auto-writers (JCT ingester, openaccess.nl scraper, reconcile) deleted from the codebase, roughly 1,400 lines including tests, so hand-curated data can never be overwritten. Decision 15 dropped the "quality bar" presentation filter for the plain cutoff `works_2020_plus > 3`, after measuring that the bar put 138,834 of 177,181 journals in default scope against a 50-70k estimate. Docs left version control the same night.

That afternoon the project turned to relevance: pgvector compiled into the Postgres image (`c40f38b`), bge-small embeddings, semantic search, and three cosine-ranked similar-journal lists (decision 21). Oct 24 was the quietest day of the project, two commits, both polish: semantic-search paging and an accessibility sweep.

### Oct 25-26, 2026: toward "any Dutch institute"

Oct 25 (19 commits) reframed the goal: a fresh instance should fill itself once the environment is set, so a new university can boot the stack and auto-harvest. That required partially reversing decision 14 from the day before: deal auto-harvest came back (`2f9b5f8`, `c00b587`) while the hand-curated register survived in the live database. The same day added the bootstrap service (`28bde61`), the data window as environment variables, a password-protected harvest-inspection admin panel (`acb16bc`), and DEPLOYMENT.md with a Groningen reference stack (`f52ae6d`).

Oct 26 was the biggest early day: 51 commits. The multi-institution restructure designed in `docs/multi-institute.md` was executed the same day in five phases (`0ea63ba` through `8d20bb8`), ending with the Groningen stack's own retirement (`2c2d54b`). The default-institution concept was dropped entirely (`08e4356`). Then people arrived: the author roster ingested wholesale from ut-metadata (decision 23), a confirmed-affiliation gate defaulting on (decision 24), preprints and books excluded from every count (decision 25), and author topics re-weighted per source (decision 26). UT's publication window moved to 2010-open, and one import (`54d90d9`) copied 75,505 OpenAlex payloads plus 139,892 Pure and 70,051 Crossref raw records over from ut-metadata, with OpenAIRE re-confirming 73,501 DOI identities.

### Oct 27-29, 2026: canonical sources, a dead host, and the catch-up

Oct 27 (13 commits) was correction day. Publishers were canonicalized to top-level lineage after Lippincott Williams & Wilkins resolved to Wolters Kluwer on screen; deals were attributed to the latest known publisher with flip flags for contracts that age; and journal OA color began to be observed from recent works after a fully-OA MDPI journal showed as "closed". The last commit of the streak landed at 22:24 (`0712412`). Then the production host, a LAN box at `192.168.2.35`, went dark; ssh attempts recorded on Oct 28 and 29 time out. The stack came back on the local workstation. The move itself was done by hand and is undocumented; database freshness stamps suggest the data was migrated rather than re-harvested, likely following DEPLOYMENT.md's export-and-restore procedure.

Oct 28 is the one day with zero commits, and still not idle: the feedback system (ported at the owner's request from another project) and the DOAJ canon rework were built entirely in the working tree, and the live database applied migration `0030_doaj_limitations` before that file existed in git. Oct 29 (12 commits) caught version control up (`b41b753` feedback, `29ad8d4` DOAJ canon with the new generic OA bucket), started the documentation wave that produced the tracked overview, and ran a structural audit that became seven untracked implementation plans (`plans/001-007`).

### Oct 30-31, 2026: structural repayment and the corpus repair

Oct 30 is the biggest day so far: 63 commits. Much of it executes the audit plans: one vocabulary module with validation at the API boundary, regenerated frontend API types, CHECK constraints that make illegal data states unrepresentable (migration `0033`), shared query/facet/cache logic extracted into `services/`, and the split of god files into packages. The same day shipped decisions 27 and 28, the standalone author path: local stores, a ported identity-resolution cascade, an admin identity-review surface, and an ingest cutover, so journal-browser no longer depends on the UT-local ut-metadata database for authors. CI was unbroken, ty joined the toolchain, AGENTS.md and dependabot arrived.

Oct 31 (36 commits by evening) ran the repair chain the new author path exposed. The CERIF publication store had frozen at 2021-era records, leaving 2021 coverage at 2%, so it was re-swept to full coverage, author lists were backfilled (358,376 edges over 155,692 works), and 591 of 634 stranded roster authors recovered confirmed identities. Harvesting of the Pure portal org tree began the same day. Performance work landed too: guards around HNSW queries, skipped denorm refreshes for unchanged rows, a `journal_flags` bloat reclaim, and a chunked identity upsert under asyncpg's 32767-parameter cap.

### November 1, 2026: hardening the review surfaces

November 1 opened with serving polish: structured JSON logging with request ids and
credential redaction (`1ef31ae`), advisory dependency scans plus local pre-commit gates
(`35ae461`), a droid QA skill with a CI workflow (`b2ddd64`), and the first generated wiki
(`d223433`). The publisher and orgunit directories gained sort direction, a works filter,
has-works facet counts, a cached orgunit snapshot (`d428226`), and Open Access NL profile
links on journal and publisher detail pages. The author cascade picked up enforcement of the
weak-rung single-ORCID rule (`8e69afb`), with the validation script rewritten as a read-only
probe (`990a714`).

The day's last stretch came out of an implicit-state-machine audit that mapped every status
column, tri-state boolean, and hand-rolled fetch machine in the codebase. It landed in four
commits: `start_run` now closes stale `running` harvest rows so a killed job cannot leave a
phantom run (`3b0f3b0`); every admin status flip on the review surfaces appends to a new
append-only `status_changes` audit table, the work-identity review loop moved in-app behind
`GET/PUT /admin/work-identities`, and the deal curation dismissal became reason-aware —
`deals.curation_resolved_reason` records what was dismissed so the harvester suppresses
exactly that reason instead of blanket-suppressing every future one (`9756103`); and the
frontend admin panels swapped their five hand-rolled fetch state machines for one shared
`useAdminResource` hook, gaining a work-identity review panel on the way (`bd5aeca`,
`bf2a852`).

## Longest-standing features

- The scaffold still holds. `db.py`, `main.py`, `docker-compose.yml`, and the frontend shell all date to the first commit (`e4e57a6`, Oct 22, 2026) and remain in daily use; the `/healthz` endpoint has answered since that first `main.py`.
- The ISSN-L backfill (`488b741`, Oct 22, 2026) is the oldest harvester still on the critical path. It runs as a bootstrap step and resolves deal-coverage ISSNs; the rows it cannot resolve (8 in the live database) keep a `needs_curation` flag.
- The Oct 22 OpenAlex sweep is the data foundation: 177,181 journals swept once, and per the issues register in `docs/data-pipeline/OVERVIEW.md` nothing refreshes that corpus yet. Every later feature denormalizes onto it.
- The landing-zone rule (decision 3, Oct 22, 2026), raw payloads first and normalization after, is why several deprecations below were survivable: purged deal rows were re-derivable from landing copies.
- Two flag-gated scaffolds from Oct 22 are still parked: `journal_citations` (superseded in the product by embeddings) and the Jisc Open Policy Finder harvester (waiting on an API key).

## Deprecated features

- **The quality bar.** Introduced Oct 22 (decision 12) as "collect everything, present a curated default scope". Dropped Oct 23 (decision 15) when measurement showed it scoped 138,834 of 177,181 journals, far above the intended 50-70k. Replaced by the cutoff `works_2020_plus > 3`, which is still current.
- **The deal auto-writers, deleted then partly restored.** Decision 14 (Oct 23, `37258de`) deleted the JCT ingester, the openaccess.nl scraper, and reconcile so curation could not be overwritten. The logic reversed on Oct 25 (`2f9b5f8`, `c00b587`): a fresh instance cannot hand-curate, so auto-harvest returned for bootstrap purposes. The live database still serves the hand-curated 16-deal register, and the restored pipeline has never re-run there.
- **Overeager diamond.** Decision 17 (Oct 23) derived journal OA type with "in DOAJ without APC evidence = diamond". A bug chain undermined it: OpenAlex `apc_prices` were stored but never mapped and `homepage_url` was never populated, so priced journals looked free and claimed diamond. The Oct 27 observed-color amendment did not fully fix the class, so the owner reworked the model on Oct 28: DOAJ became the canonical OA source, and journals with OA evidence but an unknown OA model got a new `generic` bucket (migrations `0029`/`0030`, committed as `29ad8d4` on Oct 29).
- **The ut-metadata works DSN surface.** Decision 18 (Oct 23) routed Twente publication lists through a second, live ut-metadata Postgres over a DSN. Commit `08e4356` (Oct 26) dropped the external works DSN surface in favor of copied raw records; decisions 27-28 (Oct 30) removed the remaining dependency, the author ingest. ut-metadata now survives only as an optional accelerator behind `author_source=utmd`; by default nothing reads it.
- **The Groningen deployment.** Added Oct 25 as a reference second stack (`f52ae6d`), retired Oct 26 (`2c2d54b`, with the design doc updated in `edf6852`). Multi-institution survived as data rather than infrastructure: a `rug` institution row remains in the shared database, but no second deployment exists.
- **The journal-citations scaffold.** Built Oct 22 (`488b741`, flag-gated) for citation-based similar journals, superseded in the product a day later by embeddings and cosine-ranked lists (decision 21, Oct 23). It remains behind `JB_ENABLE_JOURNAL_CITATIONS`, still awaiting a turn-on-or-delete decision.

## Major rewrites

**The multi-institution restructure (Oct 26, 2026).** Designed in `docs/multi-institute.md`, one of the two docs that stayed tracked: one deployment, a shared institution-neutral core, per-institution works corpora and windows, and `/{code}/` URL paths, with "one coordinated cutover, no compatibility aliases". It was executed the same day in five phases, `0ea63ba` through `8d20bb8`: shared-core schema (migration `0019`), a two-layer bootstrap DAG, institution-scoped routes with generic renames (`twente_works` became institution-neutral), the `/{code}/` segment with a landing chooser, and the Groningen retirement. Not everything in the plan survived contact with the schema: the planned `is_default` institution flag was dropped (migration `0022`), so no institution owns the root path.

**The standalone author path (Oct 30, 2026).** Authors had been ingested wholesale from the UT-local ut-metadata database since Oct 26 (decision 23). Decision 27 declared that journal-browser must run standalone, since other institutions will not have a ut-metadata; decision 28 shipped the replacement as migration `0035` plus four new bootstrap steps: CERIF org and person stores, an `openalex_works` projection, and durable `author_identities` review rows. The resolution cascade was ported almost one-to-one from ut-metadata (orcid-exact, then name-exact, initials, family, and fuzzy, gated by org-tree affiliation) with a CJK homonym guard added, and `author_source` selects the backend, with `utmd` kept as the legacy option. The first live end-to-end run the next day immediately surfaced the frozen CERIF store described above.

## Growth trajectory

Commits per day, Oct 22 through Oct 31, 2026: 29, 23, 2, 19, 51, 13, 0, 12, 63, 36. That is 248 commits in nine days, one author. The Oct 30 peak is partly mechanical: executing the audit plans produced long runs of small, scoped commits, and the shared test-factory change alone was spread across roughly twenty.

- Tests: 12 test files existed on day one; 50 were added across the ten days; 47 sit in the tree now, all running against a throwaway Postgres database per process.
- Schema: the initial migration plus 43 numbered revisions by Oct 31 (head `0042`). On Oct 29 the live database briefly ran ahead of git, its alembic head pointing at a migration file that was not yet committed.
- Frontend: the Oct 22 scaffold had an app shell only. The per-institution tree (`frontend/app/[inst]/`) landed Oct 26 (`8d20bb8`) and now carries eight page groups: home/search, journals, author, publisher, orgunit, deals, docs, and about. The admin area grew from a harvest-inspection panel (Oct 25) into settings, deal curation, author identity review, feedback triage, and run inspection.

Related pages: [Fun facts](fun-facts.md), [By the numbers](by-the-numbers.md), [Data pipeline](systems/data-pipeline/index.md).
