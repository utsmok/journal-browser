# Research: the current WUR Journal Browser

Sources inspected on 2026-10-22 (live, via managed browser + curl):
`library.wur.nl/WebQuery/jbrowser`, `WebQuery/wurbrowser` (listing + detail),
`/javascript/jbrowser.js`, Sherpa/JournalTOC proxy endpoints.

## What it is

The **UKB/Open Access Journal Browser** is a shared service hosted by the WUR library
(WebQuery 7.35.7, server-rendered Perl-era stack with a Vue 2 sprinkling). Every Dutch
institution gets its own entry point via redirect: `WebQuery/jbrowser` sets a
`defaultLibrary` cookie and redirects to `WebQuery/<lib>browser` (e.g. `wurbrowser`,
`utbrowser` for Twente). One shared database, per-institution views.

## Scale

- 49,030 journals in the WUR view (`?title=*`), ~30,000+ claimed in the About dialog.

## Search & facets (listing page)

- Free-text search: words in title, or all fields.
- Facets with live counts:
  - **Open Access costs**: No costs for WUR authors (26,137) / Discount (213) /
    Full costs (8,854) / Costs unknown (13,826) — *per institution*; the page carries
    facet counts for all institutions behind a "more..." expander.
  - **Open Access journals**: Open Access supported (35,670) / unknown (13,360)
    — Sherpa/DOAJ-derived OA status.
  - **Quartile**: Q1–Q4 (Scopus/CiteScore based, ~22.9k journals have one).
- Sorts: Cited by WUR, Publications by WUR, CiteScore, SNIP, SJR, Title (A-Z/Z-A).
- Marked list (checkbox per result, persisted per session).
- Pagination 20/50/100.

## WebQuery URL grammar (server-rendered, no JSON API)

- `?title=*` — list all; `?q=<term>`-style free search; `?deal/name==<code>` — filter by
  deal (deep-linked from openaccess.nl, e.g. `deal/name==AIP`, `deal/name==TFOpenSelect`).
- `wq_flt=<field>&wq_val=<value>` — facet filter; `wq_srt_desc=<field>` / `wq_srt_asc=` — sort;
  `wq_max=N` — page size. Detail page: `/WebQuery/wurbrowser/<numeric-id>`.

## Journal detail page sections

1. **Header**: title, publisher, publication year range, print/e-ISSNs, subject categories
   (Scopus ASJC-style chains), journal homepage link, JournalTOCs email-alert subscribe.
2. **Similar Journals**: co-citation ranking based on *that institution's staff* citations,
   with absolute citation counts split per WUR science group (ASG/AFSG/ESG/PSG/SSG) and a
   per-journal APC-cost column. Genuinely local/unique feature.
3. **APC Discount**: full deal narrative — participating institutions, discount %,
   corresponding-author rule, allowed publication types, workflow link, deal end date
   (`valid until 2026-12-31`), last-updated stamp.
4. **Green Open Access**: Taverne-amendment note + Sherpa "Open Policy Finder" record
   rendered client-side (Vue): permitted versions, embargoes, licenses, conditions,
   funder prerequisites. Via WUR proxy `/php/open_policy_finder.php?issn=` (live Sherpa v2
   JSON). The JournalTOCs proxy (`/WebQuery/toc/json`) is **broken** (server error) —
   recent-articles and alerts currently rot.
5. **Metrics**: JCR impact factor (login-gated) + Scopus 2025 metrics: SJR, SNIP, CiteScore,
   per-ASJC-category rank, CiteScore percentile, quartile, "9 out of 180" style ranks.
   Disclaimer: "can't be used for Tenure Track credit calculation".
6. **WUR Metrics**: "Cited by WUR staff: N times (2021–2023)" (3-year window) and
   "Publications by WUR staff since 2024: 106".
7. **Recent Articles**: from JournalTOCs (currently broken).

## Data sources per the About dialog

1. VSNU/UNL deal journal lists (national) + per-university local deal lists
2. Journal Citation Reports (JCR)
3. Scopus (journal list, metrics, subjects)
4. DOAJ
5. Per-institution citation data (citations to journals from that university's output)
6. Sherpa/Romeo (green OA conditions)
7. JournalTOCs (recent articles/alerts)

## Weaknesses observed

- Ancient stack (WebQuery 7.x, jQuery/Vue 2 mix), no public API, very slow responses
  (detail pages 30–55 s in testing), broken JournalTOCs integration.
- Scopus-licensed metrics gate parts behind institutional login; quartiles only for
  Scopus-indexed journals (~47% of the list).
- Similar-journals is the only "discovery" aid; there is a journal-recommender dialog
  stub (`#opendialog_journalrecommender` in jbrowser.js) of unclear status.
- Deal narratives are unstructured blobs; caps are communicated via ad-hoc news notes.
