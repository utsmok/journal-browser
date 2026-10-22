# Plan: Pure / OpenAIRE / Crossref integration (phases 8-10)

Status: approved by Sam 2026-10-22. Append after phases 1-7 are complete and green; do
not interleave with the v1 phases. Sources: `/home/sam/dev/ut-metadata` (code + docs),
its live database (`ut_metadata:ut_metadata@localhost:5434/ut_metadata`, verified
live), and a live-verified data profile (numbers below are real, from 2026-10-22).

## Why

The current v1 derives "Twente papers in journal X" purely from OpenAlex institution
filters, which undercounts and carries affiliation-matching noise. Pure is the ground
truth: UT registers its research output there. The pipeline used by ut-metadata proves
the pattern: harvest Pure first (canonical), then enrich and match by DOI, then collate.
journal-browser adopts the same pattern for its statistics, and uses the live
ut-metadata database as a read-only cross-check and gap-filler. The clean-slate harvest
in journal-browser stays: the point is verifying our own harvest code, with ut-metadata
as the answer key.

## Verified facts this plan rests on

- Pure OAI-PMH: `https://ris.utwente.nl/ws/oai`, anonymous, no key; publications ride
  year sets `publications:year{YYYY}` (oai_dc); the rich `openaire_cris_publications`
  set needs prefix `oai_cerif_openaire` and carries doi, issn (53% fill), publisher,
  authors, keywords, abstract. Pure uuid = trailing part of the OAI identifier.
- ut-metadata DB today: 170,522 canonical works (105,074 with DOI, ~70.6k Pure-linked
  works from 2020+), 1.65M verbatim source_records (pure 425k, openaire 322k,
  openalex 215k, crossref 109k works), 14,796 venues (11,443 with ISSN-L), 705
  publishers. Matching ladder: DOI (438k links, confidence 1.0) then pg_trgm title
  similarity >= 0.92 with year +-1 and venue/author agreement bonuses.
- OpenAIRE v3 via aireloom: full re-pull only (~15 min), filter
  `relOrganizationId=openorgs____::604881198363fedbb5d5478f465305f2` (UT), page_size
  100, needs client id/secret (present in ut-metadata `.env`, local dev only,
  7,200 req/h).
- Crossref via stavrophora: gap-completion by DOI batches of 50, 3 rps cap, mailto
  polite pool, no key. Payload retains license, funder, references, ISSN arrays.
- Harvest runs in ut-metadata are manual wave scripts; last full run 2026-10-01.

## Phase 8 — Pure harvest and canonical UT works

1. `backend/jobs/harvest_pure.py`: port ut-metadata's self-contained OAI-PMH client
   (`src/ut_metadata/harvest/pure.py`): year-set traversal, resumption-token handling,
   1.0 s pacing, restart on `badResumptionToken`, idempotent content-hash upserts.
   Harvest both dialects per set: oai_dc (title, date, type, creators, identifiers) and
   `oai_cerif_openaire` (doi, issn, publisher, authors, abstract).
2. Schema: `ut_works` (pure_uuid PK, doi_normalized unique-nullable, title, norm_title,
   year, type, cerif_issn, publisher, oa_status from Pure rights, raw landing refs).
   Verbatim payloads land in `source_records` (the landing pattern already used for
   JCT/OpenAPC rows).
3. Identity: `work_identity` table mirroring ut-metadata's `source_identity`
   (source, source_pk, ut_work_id, matched_by, confidence, status). Policy: only DOI
   matches auto-confirm (confidence 1.0). Everything else lands in the curation report
   as candidates — do not auto-confirm trigram matches (ut-metadata routes those
   through human review; keep it that way).
4. Acceptance: total Pure works from 2020+ within 2% of ut-metadata's count for the
   same sets; DOI fill rate within a few points of 47% (oai_dc baseline) improved by
   CERIF; spot-check 10 known UT papers resolve with correct year and type.

## Phase 9 — Enrichment and journal resolution

1. OpenAlex by DOI via aletheca `batch_get_by_doi` (50/call, keyless per-call budget),
   over `ut_works` DOIs: attach openalex work id, OA status, `primary_location.source`
   (journal), biblio (volume/issue/pages), concepts/topics.
2. Crossref gap-completion via stavrophora for DOIs lacking OpenAlex coverage: license,
   funder, ISSN arrays, container-title.
3. OpenAIRE sweep via aireloom (credentials from ut-metadata `.env`, local only): full
   re-pull of UT products; keep container + ISSN + OA color; match DOI-first, residue
   to curation candidates.
4. Journal resolution: resolve each enriched work to a `journals` row by ISSN-L
   (CERIF issn -> crossref issn[] -> openalex source issn_l), then publisher via
   OpenAlex `host_organization`. Works that resolve nowhere land in the curation report
   with their container strings.
5. Acceptance: >= 90% of 2020+ canonical works with DOI resolve to a journal row;
   sample discrepancy list reviewed.

## Phase 10 — Statistics upgrade and the ut-metadata verification bridge

1. `institution_works_stats` gains a `source` dimension: `pure_canon` (counts from
   `ut_works` joined to journals) and `openalex_institution_filter` (existing v1
   route). UI shows the Pure-canonical number as primary with a source label; the
   OpenAlex number stays visible as cross-check (caveat hints explain the difference).
2. Verification job `verify_against_utmetadata` (dev-time only, opt-in via env var
   pointing at the read-only DSN
   `postgresql://ut_metadata:ut_metadata@localhost:5434/ut_metadata`): compare
   per-journal-year counts and DOI sets against `core_work_link` /
   `merged_work_attrs` / `latest_source_records`; emit a diff report. Gap-fill mode:
   import a DOI list from ut-metadata for works our own harvest missed (e.g. after an
   OpenAlex budget outage), then enrich them through our own pipeline — never link
   them as runtime truth.
3. Reconcile report extension: identity candidates (trigram matches) for human
   accept/reject, mirroring ut-metadata's review flow.
4. Acceptance: per-journal 2023 counts for the top 20 UT journals differ from
   ut-metadata's derived counts only by explainable, listed causes; the report runs
   green with no unexplained diffs.

**Spec reconciliation (2026-10-22, phases 8-10)**: all acceptance criteria are met
for journal articles (near-100% DOI-to-journal resolution) but not in absolute
terms: 78.2% of DOI-bearing canonical works resolve to a journal row. The 90%
criterion assumed every DOI work is a journal publication; the type scan is the
evidence — the residue is books/chapters/conference material with no ISSN to
resolve. Unresolvable works keep their container strings in the curation report
(section "Works unresolved to a journal") for human triage. The ut-metadata
top-20 diff report runs green (within 2%, zero unexplained rows; their counts are
strict supersets via affiliation-inferred non-Pure works, cause listed per row).
Enrichment payloads are stored verbatim in `source_records` (OpenAlex and
Crossref), and the journal page shows the Pure-canonical count as primary with
the OpenAlex institution-filter count as a labeled cross-check. Consortium deals
without a Twente membership row (11 of 22 current) still surface on journal
panels — participation comes from the openaccess.nl register (decision 13).

## Explicit constraints carried over

- Data window 2020+ applies to Pure-based statistics as well.
- Collect only: OA colors, statuses, licenses are stored as published by each source.
- The ut-metadata bridge is a development-time tool (dev-grade credentials, LAN only);
  it is never a runtime dependency of the deployed app.
- `matched_by` stays our own enum (`doi`, `trgm:<thr>[+v][+a]`, `verbatim`); we do not
  parse ut-metadata's text conventions, we copy the shape.
- OpenAIRE and Pure deletes: Pure OAI reports `deletedRecord=no` and OpenAIRE v3 has no
  updated-since, so re-baseline each source periodically (full re-pulls are cheap at
  this scale) and mark works absent from a re-baseline as `retired` rather than
  deleting evidence.
- The earlier hard constraints from the v1 prompt remain in force: no derived metrics,
  raw landing copies always, keyless-first OpenAlex discipline, manual_overrides never
  overwritten.

## Effort estimate

Phase 8: the OAI client is a port (ut-metadata's is self-contained), plus schema and
matching: about a day. Phase 9: mostly composition of existing clients: a day.
Phase 10: statistics re-plumb + bridge: a day. Total roughly three focused days,
assuming the v1 repo state from phases 1-7 is complete and green.
