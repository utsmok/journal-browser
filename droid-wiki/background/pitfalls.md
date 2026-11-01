# Pitfalls

Danger zones and "why is this code weird" explanations, each verified in the current tree. Several are pinned by tests or documented in code comments; where that is the case, the file is cited. For the conventions these traps enforce, see [Patterns and conventions](../how-to-contribute/patterns-and-conventions.md).

## Operating a deployment

### The live stack is off limits

The compose project `journal-browser` (ports 3000/8000) is a live deployment: never restart it, redeploy it, or write to it. The live `journalbrowser` database is read-only for agents: SELECT is fine, DDL is not. Tests create a throwaway database per process (`backend/tests/conftest.py`) and test stacks run on separate ports via `compose.test.yml` (db on 5533, backend on 8001). The rule is recorded in `AGENTS.md`.

## Code structure

### Router include order is load-bearing

`backend/src/journal_browser/main.py` must include the admin, feedback, and docs routers before the `/{institution_code}` scoped router. If a fixed prefix lands after the catch-all, the institution scope shadows it and `/api/v1/admin` starts resolving as an institution code. The invariant is pinned by `backend/tests/test_route_precedence.py`, whose docstring states it, and the order is commented in `backend/src/journal_browser/main.py`.

### Migrations are historical record

`backend/alembic/versions/` is never reformatted (the formatters exclude it), and every migration must downgrade cleanly on a test database. The modeling rule behind the tables is CheckConstraint plus plain Text columns, never pg enums, which is what keeps downgrades reversible. Recorded in `AGENTS.md`.

### Shared logic lives in services/, never copied between routers

Query, facet, and cache logic shared by the global and institution-scoped routers lives in `backend/src/journal_browser/services/`. Copying it into a router re-creates the drift the October 30 extraction was meant to kill: two copies of a cutoff or a facet rule will diverge silently. The same rule is why the corpus cutoff and proceedings exclusion live in `backend/src/journal_browser/services/search/` rather than in each endpoint.

### Feature scaffolds stay OFF

`JB_ENABLE_JISC` and `JB_ENABLE_JOURNAL_CITATIONS` gate integrations that have not shipped. The scaffolds sit dormant behind flags that flow through `backend/src/journal_browser/settings_schema.py`, and the off state is pinned by `backend/tests/test_scaffolds.py`. Turning one on does not enable a feature; it enables a scaffold.

## Data traps

### Direct works-to-journals joins lose most rows

60% of UT works (93,069 of 154,766 at the October 29, 2026 count) have no `journal_issn_l`, mostly because they are dissertations, conference papers, or book chapters with no ISSN anywhere. Any direct join from `works` to `journals` therefore loses most rows by construction. Journal-level statistics come from `institution_works_stats` instead. This is recorded as issue 3 in `docs/data-pipeline/OVERVIEW.md` §4 with an explicit note to document it before anyone joins directly.

### oa_type is derived; works.oa_status is stored

Journal `oa_type` (gold, diamond, hybrid, generic, subscription) is computed at query time in `backend/src/journal_browser/services/search/classify.py` and never stored. Work-level `works.oa_status` is the deliberate opposite: stored as published, with Pure access states canonicalized in `backend/src/journal_browser/harvest/pure/store.py`, and never derived. The two layers answer different questions (what kind of venue is this, versus what access state did this work have), and the comments in `classify.py` record the owner decisions behind each branch.

### JCT absence is never evidence a deal does not exist

The JCT consortium sheets do not consistently enumerate members; 11 of 22 visible deals once had no Twente membership row while openaccess.nl confirmed coverage. Decision 13 (D13 in `docs/decisions.md`) makes openaccess.nl the canonical register and JCT enrichment only, so a missing JCT row must never suppress a deal that the register confirms.

### DOAJ wins in-DOAJ disagreements

Where OpenAlex claims DOAJ membership that the DOAJ sweep refutes (124 journals at the October 29 count, 3 the other way), the `doaj_*` columns from `backend/src/journal_browser/harvest/doaj.py` are canon. The residue is upstream drift, not a bug to fix locally; see issue 9 in `docs/data-pipeline/OVERVIEW.md` §4 and the `_OA_EVIDENCE` comment in `backend/src/journal_browser/services/search/classify.py`.

## Harvest and runtime traps

### Retirement runs against the sweep's run-id list

A per-year Pure sweep once retired works that other sweeps had seen, because retirement compared against the wrong set. `retire_absent` in `backend/src/journal_browser/harvest/pure/store.py` now takes the run-id list of the sweeps being reconciled, and an empty list is a documented no-op because `NOT IN ()` would retire every row. Never deletes; sets `retired_at`. Fixed in `b8574a8`.

### OpenAlex 429 storms manufacture false negatives

A rate-limit storm during DOI enrichment recorded works as `missing` identities when the request had merely been refused. The fix keeps a polite gap between chunks and uses the polite pool, with the why in the header comment of `backend/src/journal_browser/harvest/enrich.py`. Fixed in `b8574a8`.

### asyncpg returns jsonb as strings, so [] is truthy

asyncpg hands jsonb columns back as strings, so an empty JSON array `[]` passes any truthiness check. This caused a fake recovery measurement: a preview reported 634 of 634 stranded authors recovered when the real live number was 591, because an empty evidence array counted as evidence. The incident is recorded in `docs/data-pipeline/OVERVIEW.md` §3. Test jsonb values for emptiness, never for truthiness.

### Skip the embedding warmup in CI and offline runs

Importing the app preloads the roughly 130 MB ONNX model and threads a warmup encode. `JB_SKIP_EMBEDDING_WARMUP=1` skips both, which offline schema dumps and CI require; `backend/src/journal_browser/main.py` documents and implements the skip. Leave the variable unset in real deployments.

### JB_BOOTSTRAP=auto exits in seconds once journals exist

The compose default runs the bootstrap service on every `docker compose up`, but auto mode checks whether the database is already bootstrapped and exits immediately (`backend/jobs/bootstrap.py`, message: "bootstrap: journals present, nothing to do (use --always to force)"). Re-running the stack therefore never re-harvests. To force work, use `--always`, `--from <step>`, or `--institution <code>`; the semantics are in [Bootstrap DAG](../systems/data-pipeline/bootstrap-dag.md).
