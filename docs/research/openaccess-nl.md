# Research: openaccess.nl deal information

Pages inspected 2026-10-22: `/en/publishing/publisher-deals` (overview),
`/en/publisher/<slug>` (publisher page), `/en/publisherdeal/<slug>-<years>` (deal page).
Platform: Drupal 10 (droopler theme). **No JSON API** (`/jsonapi` → 404).

## What the overview page offers

One accordion row per deal (current deals first, then an archive of expired deals back to
~2016), columns: Publisher (link), short summary, deal duration, status. ~22 current deals
(ACM, AIP, ACS, AUP, Annual Reviews, Cambridge, De Gruyter Brill, Elsevier, Emerald, IOP,
IOS Press, Karger, LWW, OUP, PLOS, RSC, SAGE, Springer, Taylor & Francis, Company of
Biologists, Thieme, Wiley) plus dozens of archived ones.

## Per-deal content (accordion body + deal page)

Structured enough to model, free-text enough to need curation:

- **Parties**: publisher; participating institutions (prose list, varies per deal —
  national vs local deals); note that ACM deals are concluded *per institution*.
- **Duration**: e.g. `2025-2027`; extensions announced as updates inside the text.
- **Journal scope**: prose ("more than 404 hybrid and full OA journals", "all hybrid
  journals", named collections) + deep links *into the WUR journal browser*
  (`jbrowser?deal/name==...`) as the authoritative journal list. openaccess.nl does not
  publish journal lists itself.
- **Article types covered** ("original research articles, review articles...").
- **Caps**: capped deals flagged with a cap note and expected exhaustion date ("cap for
  2026 has been reached"); per-year cap numbers in some deals (OUP: 733/707/680;
  LWW: 270/273/276; Emerald: 101 vouchers/yr; ACS: 542/yr). Notify-me service link.
- **Workflow**: how-to text per publisher (email/affiliation requirements, license choice,
  where to click). Contract PDF links (redacted agreements on openaccess.nl).
- **Status**: open/closed, Current/Archive.

## Publisher page (`/en/publisher/<slug>`)

Clean, scrapeable structure (`.licence-data-item` blocks): one table per deal with
**Deal duration**, **per-calendar-year OA publication counts** (Elsevier: 2016–2026,
e.g. 2024: 6,752), `Status licence` (Current/Archive, `status-licentie-<id>` class),
and a **Read more** link to `/en/publisherdeal/<slug>-<years>`.

## Deal page (`/en/publisherdeal/<slug>-<years>`)

Full record per deal: title "Elsevier (2025-2027)", one-line summary, licence table
(publisher, duration, status), **License and conditions** (long text incl. participating
institutions, article types, caps), **How does it work?** (workflow steps), contract PDF
and publisher-website links.

## Scraping assessment

Stable CSS classes and predictable URLs make a targeted scraper viable (overview →
publisher pages → deal pages). Risks: free-text variance across ~60 deals, prose-encoded
institution lists, and edits-over-time (update notes inside text bodies). A **hybrid
approach** fits: scrape as raw material → human-curated structured records in our DB →
scraper alerts us when upstream text changes.

## Implementation (2026-10-22)

Implemented in `backend/src/journal_browser/harvest/openaccess_nl.py` +
`backend/jobs/scrape_openaccess_nl.py` (run: `uv run python jobs/scrape_openaccess_nl.py
[--limit N]`, sequential fetches). Overview + publisher + deal HTML land in the landing
store before parsing; deal pages become `source_records` (source `openaccess.nl`).
Domain upserts: `publishers.openaccess_nl_slug`; `deals` by natural key
(publisher, duration) with status/start/end years, per-year OA counts, summary,
conditions/workflow text, article-type and cap sentences, cap numbers (only unambiguous
year:number pairs), first openaccess.nl-hosted contract PDF, provenance, and
`needs_curation` when a deal page lacks a section or cap numbers are ambiguous.
Deals are NOT linked to JCT here — the reconcile job owns that.

Findings vs. the structure above: section markers are `<p><em><strong>Title</strong></em></p>`
with two title variants ("License and conditions" — sometimes with a trailing " :" —
and AIP's "Details and conditions of the licence"); PLOS's deal URL has no year suffix
(`/en/publisherdeal/plos`); IOP's page marks both its licences "Archive" although the
overview lists it under Current; archive-only publishers (BMJ, Brill, Frontiers,
Walter de Gruyter) are crawled too, and their older deal pages often lack sections
(flagged for curation, never fabricated).
