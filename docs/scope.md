# Project scope: Open Access Journal Browser (rebuild)

## One-paragraph description

A public search tool that helps researchers at our university answer one question:
**"Where should I publish, and what will it cost me?"** For every journal it shows whether
the journal falls under an open access publishing agreement (a "deal"), what that means in
practice (discounts, caps, article types, workflow), how our university publishes in the
journal (papers per year, OA status), and what the journal is about (subjects, metrics,
similar journals). It replaces the WUR-hosted Journal Browser
(`library.wur.nl/WebQuery/utbrowser` et al.) with OpenAlex as the sole bibliometric data
source, dropping all Scopus dependencies.

## In scope

1. **Deal data (the core)**: structured database of open publishing deals relevant to our
   institution — parties, duration, status, journal lists (ISSN-level), caps, article
   types, workflow text, contract links — assembled from the cOAlition S JCT public data
   (CC0), the ESAC registry, and scraped/curated openaccess.nl content.
2. **Journal search & browse**: free-text + facet search over ~200k OpenAlex sources
   (facets: deal coverage, OA status, DOAJ listing, subject/topic); journal detail pages.
3. **Institution statistics**: papers per year in each journal by our authors, OA-status
   breakdown, and institution-level trend charts — computed from OpenAlex works.
4. **Journal context**: OpenAlex metrics (`2yr_mean_citedness`, `h_index`), topics,
   counts-by-year trends, APC list prices, SJR/quartiles via the open scimagojr CSV,
   similar journals (co-citation by our staff + topic similarity).
5. **Refresh infrastructure**: scheduled ingestion jobs (OpenAlex, JCT dump, scimagojr,
   openaccess.nl scrape) with a raw-landing-zone + normalized-tables design and a
   curation workflow for deal data that cannot be derived automatically.

## Out of scope (for v1)

- Multi-tenant/multi-institution views (the old tool serves all Dutch universities; v1
  targets our institution only) — the schema keeps institution as data, so expansion is
  configuration, not surgery.
- User accounts, marked lists, email alerts (old tool has them; revisit after v1).
- Green-OA/self-archiving policy display (Sherpa replacement) — separate integration,
  noted as follow-up.
- JCR/Scopus metric parity — intentionally replaced by open metrics.

## Success criteria

- A researcher can find a journal by title/ISSN and see within one page: deal coverage
  for our institution, cost implication, caps if any, and where to read the details.
- Every deal shown links to its openaccess.nl page and contract PDF; the deal's journal
  list is traceable to its source (JCT data URL or manual curation record).
- Journal statistics verified against OpenAlex queries for a sample of known journals.
- Public read-only API (`/api/v1/...`) — no more screen-scraping a Perl app.

## Key users

- Researchers choosing a venue (primary).
- Library/open-access staff maintaining deal information (curation interface, v1.1).
