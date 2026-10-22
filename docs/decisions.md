# Decisions log

## Settled decisions (with owner sign-off 2026-10-22)

1. **Deal journal lists come from the cOAlition S JCT public dump (CC0), amended with
   openaccess.nl data.** Never scrape the old journal browser; go to the sources.
2. **Stack**: FastAPI + SQLAlchemy 2 (async) + asyncpg on Postgres 17, Next.js,
   docker compose, `uv`.
3. **Ingestion as plain `uv run` jobs** in `backend/jobs/` with a raw landing zone,
   audit rows, and permanent local copies of crucial data.
4. **Clients: `aletheca` (OpenAlex), `aireloom` (OpenAIRE), `stavrophora` (Crossref)**
   — our own bibliofabric family; aletheca is on PyPI and used in depth by
   `ut-metadata` (see `docs/research/aletheca-ut-metadata.md`).
5. **Metrics: collect only.** Register what OpenAlex, scimagojr, and OpenAPC publish.
   No derived substitute metrics in v1.
6. **Institution: University of Twente, ROR `006hf6230`.** v1 is single-institution;
   ROR-keyed schema keeps later multi-institution configuration possible.
7. **Data window: 2020 to now** for all works-derived data.
8. **API budget discipline**: minimize keyed OpenAlex calls; plain entity lookups
   (`W…`/`S…` IDs) need no key. The free key in `~/.zshrc` (`OPENALEX_API_KEY`) is for
   cursor-paged harvests only.
9. **Deployment (PoC)**: private LAN server, straight `docker compose up`; production
   concerns deferred.
10. **Licensing/attribution**: project private for now; no explicit attribution UI yet,
    but every record links to its upstream source and stores a local raw copy.
11. **Frontend styling (2026-10-22)**: openaccess.nl-inspired theme for the initial
    implementation, built on Tailwind v4 CSS variables + shadcn-style components +
    TanStack Query/Table, patterns copied from the TCRC frontend. Re-theming to UT
    branding is a token-block swap (TCRC's audited UT palette is prepared for that).
    Typography: Inter + Montserrat (both SIL OFL, self-hosted via next/font).
12. **Corpus policy (2026-10-22): collect everything, present a quality bar.** The
    OpenAlex sources sweep is unfiltered — no upstream filtering changes. The
    presentation layer defaults to a quality bar: `type='journal' AND issn_l IS NOT
    NULL AND (is_in_doaj OR in_scimago OR deal coverage OR is_active_recently)`,
    where `is_active_recently` means the latest `counts_by_year` entry with
    works > 0 is >= 2020. Flags are derived locally at upsert time (zero extra
    API calls); deal coverage stays relational. `scope=all` returns the full
    corpus; the frontend defaults to the quality bar with a visible "include all
    journals" toggle and an "outside quality bar" badge in all-scope view.
    Expected band: ~50-70k in the default scope vs ~168k for the full corpus.

## Open questions

1. **Jisc Open Policy Finder API key**: needed for green-OA policy integration
   (`https://api.openpolicyfinder.jisc.ac.uk/retrieve`, `x-api-key` header). Sam will
   request it; integration starts when the key arrives. (Say the word and the harvester
   scaffold is next.)
2. **OpenAPC harvest frequency**: dataset updates are release-based; refresh monthly?
   (default: monthly)
3. **Which OpenAIRE/Crossref fields earn their place**: both are in scope per decision 4,
   but the concrete field selection per entity is open until the harvesters run; the
   `ut-metadata` implementation is the reference.

## Implementation notes (2026-10-22 build)

- **ESAC registry not scraped**: esac-registration.org renders via JS; deal↔ESAC
  identity comes from the JCT dump (esac_id) joined to openaccess.nl narratives by
  publisher alias + duration overlap, tiered: Twente-bearing agreements first, then
  Dutch consortia (ukb/surf/nl), foreign consortia never merge. UKB/SURF joint deals
  often omit member lists; such merges get a "verify Twente participation" curation
  flag instead of asserting coverage.
- **OpenAPC Twente rows carry euro=NA** in the source data for all 297 Twente
  evidence rows (2020+); cost evidence for Twente articles therefore comes from the
  journal-level aggregates, not per-article amounts.
- **scimagojr.com is Cloudflare-hard** (403 for httpx and curl-cffi impersonation;
  headless Chromium fails the challenge). Exports are fetched once through the
  user's Chrome relay (in-page same-origin fetch) and landed as
  `landing/scimagojr/export_<year>.csv` (latin-1, semicolons — parse with the csv
  module; naive splits corrupt rows where quoted fields contain semicolons).
- **JCT `institutions_name_key` collisions**: different RORs share display names
  (e.g. "Open University"); the ingester suffixes the ROR id instead of failing.
- **OpenAIRE/Crossref enrichment corpus** is bound to the deal+Twente-active journal
  set, not the full 177k corpus.
- **counts_by_year entries use `works_count`** (OpenAlex published key). A `works`
  key guess made every activity flag silently false — caught by the quality-bar
  count sanity check (0 active journals).
- **Quality-bar band (decision 12)**: the specified predicate (any work since 2020)
  puts 138,834/177,181 in the default scope, above the ~50-70k estimate. The
  predicate is as agreed; if a tighter default is wanted, tighten the activity
  definition (e.g. minimum works in window) — data supports either.

## Historical notes

- 2026-10-22: initial research phase. An early draft of this project assumed WUR as the
  institution (ROR `04qw24q55`); corrected to Twente (`006hf6230`).
- 2026-10-22: "cited by Twente staff" (two-step W-id batching) demoted to a secondary
  step: scaffold included, full runs wait for an explicit go.
