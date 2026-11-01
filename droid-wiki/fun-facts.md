# Fun facts

Small true things from journal-browser's first nine days (Oct 22-31, 2026). Each is verified against commit timestamps or the dated registers in `docs/`, most of which is gitignored, though the tracked `docs/data-pipeline/OVERVIEW.md` records several of these itself.

### 248 commits in nine days

The first commit landed on Oct 22, 2026 at 12:58, titled "Scaffold: FastAPI+Next.js+docker skeleton, research docs, implementation plan". By the evening of Oct 31 the repo held 248 commits from a single developer, committed mostly as `utsmok` and five times as Sam or Samuel Mok. The busiest day was Oct 30 with 63 commits; the quietest was Oct 28 with zero, though that day still produced two features (see the migration story below).

### The Emerald deal, hand-rebuilt from paper

On Oct 22, 2026 the JCT dump linked the Emerald agreement (`eme2025ukb`) to an Elsevier journal sheet, the wrong publisher entirely. The deal's 311 coverage rows were rebuilt by hand from the signed contract: the scanned PDF went through OCR into a spreadsheet, all 311 titles matched OpenAlex Emerald sources, and the rows landed as `source='manual'` (`4ba470b`). The contract spreadsheet is archived in the landing zone. Per the Oct 29 overview, the JCT sheet is still wrong upstream.

### Five researchers named Xiang Zhang

During the standalone author path's first live runs on Oct 31, 2026, a blanket-confirm attempt for "fragmentation twins" (alternate OpenAlex profiles of the same person) merged five distinct Xiang Zhang profiles in preview. The fix is a ledger gate: an alternate id may auto-confirm only if it never co-occurs with the primary on any work, and the ORCID evidence across primary and alternates names at most one human (`b1948ce`, Oct 31, 2026). Common-name fragmentation is exactly the class the gate prevents.

### The bug that faked a perfect recovery

A repair-day claim that 634 of 634 stranded roster authors had recovered confirmed identities turned out to be a measurement bug: asyncpg returns jsonb values as strings, so an empty array arrived as the string `'[]'` and passed a truthiness check. SQL verification put the real number at 591 of 634, and the remaining 43 are an honest dead end: their CERIF evidence carries no UT affiliation the org tree can close on. The overview now records that recovery was never actually preview-versus-live divergence (Oct 31, 2026).

### The migration that ran before it was committed

On Oct 28, 2026 the live database's alembic head pointed at `0030_doaj_limitations` while git HEAD predated the entire feature set behind it: the feedback system and DOAJ canon existed only as 24 modified and 11 untracked working-tree files. The database was running schema ahead of version control until Oct 29, when `b41b753` and `29ad8d4` committed the work. The issues register in `docs/data-pipeline/OVERVIEW.md` tracked this as its top-severity item until it was resolved.

### Scimago CSVs through a real browser

scimagojr.com sits behind Cloudflare and defeated httpx, curl-cffi impersonation, and headless Chromium, each getting a 403. The Oct 22, 2026 workaround was human: the exports were fetched once through the developer's own logged-in Chrome via an in-page same-origin relay, landed as CSV files, and the parser was hardened afterward (`462cfb7`), because naive splits corrupt rows where quoted fields contain semicolons. The gzip CSVs for 2022-2024 now ship in the repo under `backend/data/scimagojr/`, so no future clone has to fight the challenge again.

One more: even the punctuation has history. Ruff's `allowed-confusables` list (added Oct 30, 2026, `efea1f1`) exempts the en dash, em dash, multiplication sign, and arrow, because harvest text uses them intentionally and the linter would otherwise flag real typography as obfuscation.

Related pages: [Lore](lore.md), [Design decisions](background/design-decisions.md).
