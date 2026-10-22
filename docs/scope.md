# Project scope: Open Access Journal Browser (rebuild)

## One-paragraph description

A public search tool that helps researchers at the University of Twente (ROR
`https://ror.org/006hf6230`) answer one question: **"Where should I publish, and what
will it cost me?"** For every journal it shows whether the journal falls under an open
access publishing agreement (a "deal"), what that means in practice (discounts, caps,
article types, workflow), how Twente publishes in the journal (papers per year, OA
status, APCs actually paid), and what the journal is about (subjects, metrics, similar
journals). It replaces the WUR-hosted Journal Browser
(`library.wur.nl/WebQuery/utbrowser`) with OpenAlex as the sole bibliometric data
source. The goal is a proof-of-concept demo for Twente first, then an open-source
project other universities can launch and run for themselves.

## Data scope

- **Time window: publication years 2020 to now, everywhere.** All works queries,
  statistics, and ingestion filters restrict to this window. Earlier data stays out
  until explicitly expanded.
- **Collect, do not derive (v1).** The system registers what sources natively provide
  (OpenAlex `summary_stats`, scimagojr SJR/quartiles, OpenAPC costs). It does not
  compute substitute metrics (CiteScore-lookalikes etc.) in v1.
- **Known data limitations are first-class data.** Every source's caveats are registered
  in a limitations registry (see plan.md), logged, and surfaced as caveat hints in the
  frontend so users see where numbers come from and what they miss.
- **Local copies of crucial data are always stored** (raw landing zone), so a source
  disappearing or changing never loses information.

## Data sources

| Source | Access | Provides |
|---|---|---|
| OpenAlex | `aletheca` (our bibliofabric-based client) | journals (sources), works/stats, topics, OA flags, APC list prices, summary stats |
| OpenAIRE | `aireloom` | OA versions, project/funder links, alternate records |
| Crossref | `stavrophora` | journal metadata, licenses, funder refs |
| cOAlition S JCT dump | CSV download (CC0) | deal → journal ISSN lists + institution RORs |
| ESAC registry | web | agreement metadata (durations, parties) |
| openaccess.nl | scrape + curation | NL deal narrative: caps, workflows, status, per-year OA counts |
| OpenAPC | CSV download (ODbL) | article-level APC/TA costs (Twente rows exist), contracts |
| scimagojr | CSV download | SJR, quartiles per ISSN |
| Jisc Open Policy Finder | REST API (`x-api-key`, key pending) | green OA / self-archiving policies; replaces the Sherpa feed the old tool proxied |

## In scope

1. **Deal data (the core)**: structured database of open publishing deals relevant to
   Twente, assembled from the JCT dump, ESAC, openaccess.nl, amended with OpenAPC
   cost evidence. Go to the original sources; never scrape the old journal browser.
2. **Journal search & browse**: free-text + facet search over OpenAlex sources (facets:
   deal coverage, OA status, DOAJ listing, topic); journal detail pages.
3. **Institution statistics**: Twente papers per year per journal (2020+), OA-status
   breakdown, institution-level trends, actual APC spend from OpenAPC.
4. **Journal context**: OpenAlex native metrics, topics, counts-by-year, APC prices,
   scimagojr SJR/quartile, similar journals (framework included; co-citation batch job
   is a secondary step, run only on request).
5. **Caveat system**: limitation registry per data source + frontend hint components.
6. **Refresh infrastructure**: scheduled ingestion with raw landing zone + normalized
   tables and a curation workflow for deal data that cannot be derived automatically.

## Out of scope (for v1)

- Per-faculty breakdowns (the old tool's WUR science-group splits; Twente equivalents
  are not part of v1).
- Multi-tenant deployment; the schema keeps institution as data (ROR-keyed) so the
  open-source release can make it a configuration option.
- User accounts, marked lists, email alerts.
- Any metric derivation beyond collecting what sources publish.

## Success criteria

- A researcher can find a journal by title/ISSN and see within one page: deal coverage
  for Twente, cost implication, caps if any, and where to read the details.
- Every deal links to openaccess.nl and the contract PDF; every journal list is
  traceable to its source (JCT data URL or curation record).
- Every displayed number carries its source and its registered caveats.
- A demo for Twente runs with `docker compose up` on a LAN server, and the README is
  good enough for another university to stand up their own instance.

## v1 parity target vs the live UT journal browser

Verified end-to-end on 2026-10-22 against a fresh `docker compose up` stack
(screenshots under `frontend/docs/screenshots/`).

| Capability | Live tool | v1 (this project) |
|---|---|---|
| Journal search + facets + sorting | yes | yes (facets: deal coverage, OA status, DOAJ, topic, quartile; quality-bar scope by default per decision 12, full corpus behind `scope=all`) |
| Deal coverage + cost implication per journal | yes | yes (JCT + openaccess.nl; better structured) |
| SJR + quartile | yes (Scopus-based) | yes (scimagojr) |
| CiteScore / SNIP / JCR IF | yes | no; OpenAlex `2yr_mean_citedness` + `h_index` instead, labeled |
| Publications per year per journal (institution) | yes | yes (2020+ window) |
| Cited-by-institution counts | yes | deferred: scaffolded, runs on request |
| Similar journals | yes (co-citation) | deferred: scaffolded, runs on request |
| Green OA / self-archiving policy | yes (Sherpa) | blocked on Jisc API key (phase 6) |
| OpenAPC cost evidence | no | yes (v1 addition) |
| Marked list, alerts, SSO login | yes | out of scope for v1 |

## Key users

- Twente researchers choosing a venue (primary; demo audience).
- Library/open-access staff maintaining deal information (curation report).
- Other universities (open-source adopters, post-PoC).
