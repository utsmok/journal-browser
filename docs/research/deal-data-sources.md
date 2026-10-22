# Research: open data sources for deal → journal mappings

The core question of this project: *which journals are covered by which open publishing
deal for our institution?* openaccess.nl describes deals in prose but never lists journals.
These open sources do.

## 1. cOAlition S Journal Checker Tool (JCT) public data — primary

- Index: https://journalcheckertool.org/transformative-agreements/ (CC0)
- TA Index CSV: one row per agreement — ESAC ID, relationship name, end date,
  "corresponding-authors only" flag, **Data URL**, last-reviewed date. 605 rows on
  2026-10-22.
- Per-agreement Data CSV (from Data URL): two column groups — **journals** (name,
  print ISSN, online ISSN, first-seen, last-seen) and **institutions** (name, **ROR ID**,
  first-seen, last-seen). Verified live with `kar2025surf` (Karger–SURF 2025-2027): 94
  journals, all Dutch universities + UMCs with ROR IDs, including WUR.
- Only includes *reviewed, Plan S-compliant* agreements; missing = under review or not
  compliant. Current agreements only; historical snapshots preserved by `njahn82/jct_data`
  (weekly since 2022) and the Zenodo dataset `zenodo.org/records/15308680` (1,043
  agreements, 17,199 journals, 5,355 institutions, plus matched articles).
- ISSN normalization to ISSN-L is required (the kbopenbib dataset shows the method).

## 2. ESAC Agreement Registry — agreement metadata

- https://esac-initiative.org/about/transformative-agreements/agreement-registration/
  (renamed "Registry of Open Publishing Agreements")
- Community-curated: publisher, consortium, ROR, period, cost data for each agreement.
  Provides the ESAC IDs used by JCT; fills duration/party metadata.

## 3. openaccess.nl — the NL narrative layer

As documented in `openaccess-nl.md`: statuses, caps, participating institutions (NL),
workflow texts, contract PDFs, per-year OA article counts per deal. Not machine-readable —
scrape + curate.

## 4. Gap-fillers

- **Publisher-side lists**: OUP/CUP etc. publish their deal journal lists (linked from
  openaccess.nl deal pages) — manual curation fallback.
- **DOAJ**: full-OA journal attributes (license, APC) to enrich.
- **Local deals** (e.g. ACM agreements concluded per institution): likely absent from JCT;
  need manual curation against openaccess.nl text.

## Recommended pipeline

1. Ingest JCT index + per-agreement CSVs → `deals`, `deal_journals` (via ISSN-L),
   `deal_institutions` (via ROR).
2. Scrape openaccess.nl → `deal_metadata` (cap text, workflow, contract URL, status,
   per-year counts) linked to the same agreement (publisher + duration matching).
3. Curation UI/report listing mismatches (deal on openaccess.nl without JCT row, etc.)
   for the library staff to resolve; manual overrides stored in DB, never overwritten
   by re-runs.
