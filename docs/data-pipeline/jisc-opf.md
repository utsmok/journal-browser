# JISC Open Policy Finder (OPF) integration

Data pipeline analysis for the JISC OPF harvest, landed 2026-11-02.
OPF is the Jisc service that curates publisher self-archiving policies
(green OA routes per journal version). It adds a dimension no other source
in this stack provides: what each publisher allows authors to do with
submitted, accepted, and published manuscripts.

## What was landed

Full sweep of all six OPF item types into landing tables
(`jisc_policies`, `jisc_publishers`, `jisc_funders`, `jisc_repositories`,
`jisc_publisher_rors`, `jisc_funder_groups`), then normalized onto
`journals.jisc_policy` (jsonb) for journals matched by ISSN.

| Measure | Count (live, 2026-11-02) |
|---|---|
| OPF policy records (landing) | 3,875 |
| Publisher records | 3,484 (202 with ROR links) |
| Funder records | 202 (+ 5 funder groups) |
| Repository records | 6,239 |
| Journals with `jisc_policy` | 27,666 (15.6% of 177,181) |
| Open access prohibited | 39 |

## Route semantics

Each journal carries up to three version routes (`submitted`, `accepted`,
`published`). Per route OPF states permitted locations, repositories,
licenses, embargo months, and per-entry `additional_oa_fee` values.

- `fee_only` (derived): the route states fees and every fee-stated entry is
  `yes` — the publisher only permits this version behind an OA fee. After the
  correction below, 12,065 routes are fee-only; 11,996 of them are
  `published` routes.
- `allows_sa_*`: the route exists and is not fee-only. Live counts:
  submitted 19,579, accepted 20,816, published 14,728.

An earlier normalization run (pre-fix) computed these counts with a lookup
that crashed on all-free routes and silently marked nothing fee-only; the
corrected normalizer (`jisc_normalize.py`, `fee_yes.get(version, 0)`) was
re-run live. Browser-visible effect: "published free" journals dropped from
~26.7k to 14.7k because fee-only published routes no longer count as green.

## Green OA definition

`green_oa` is a best-route bucket: the freest permitted version wins
(`submitted` > `accepted` > `published`). `none` means in OPF but either
prohibited outright or with no free route of any version: 87 journals live
(11,996 is only "published route is fee-only" — most of those journals still
self-archive an earlier version free, and 942 have no published route at
all). A journal with `open_access_prohibited` lands in `none` even if route
data exists — prohibition wins over routes.

## Cross-source overlap

- 8,244 of the 27,666 covered journals are also in DOAJ (`doaj_in_doaj`,
  the authoritative DOAJ harvest; OpenAlex's `is_in_doaj` flag says 8,273).
  OPF adds policy detail DOAJ lacks (DOAJ describes the journal's own OA
  terms, not the hybrid publisher's self-archiving terms).
- Publisher ROR links (202) join to `publishers` rows; funder ROR/FundRef
  identifiers join to the new `openalex_funders` / `openaire_funders` canon
  tables (harvested separately, see `harvest_openalex_funders.py` /
  `harvest_openaire_funders.py`).

## Refresh

```bash
cd backend
uv run python jobs/harvest_jisc.py         # full sweep to landing
uv run python jobs/normalize_jisc.py       # landing -> journals.jisc_policy
```

Both are idempotent; the sweep re-reads the whole OPF universe, the
normalizer rewrites `jisc_policy` rows it can match. Jobs read
`backend/.env` (`JB_JISC_API_KEY` required; `DATABASE_URL` defaults to the
local test stack at `localhost:5433`).

## Caveats and uncertainties

- **Policy currency**: OPF policies are curated and periodically re-reviewed
  by Jisc; they change under our feet between refreshes. Surfaced to users as
  the `jisc-policy-currency` caveat on every card.
- **License verbatim**: route conditions and licenses are shown verbatim
  (CC BY-NC-ND content license) — never paraphrased — per the
  `jisc-cc-by-nc-nd` caveat.
- **Fee nuance**: `additional_oa_fee` is per-entry, not per-route; a route
  with mixed yes/no entries stays non-fee-only. Routes with no fee statements
  at all are also non-fee-only (all-free routes never entered the old
  fee_yes lookup — the bug above).
- **Embargo**: OPF provides embargo months per route when stated; many are
  null. Absence is not "no embargo".
- **Junk digit ISSNs**: OPF matches on the 8-character ISSN string; journals
  with checksum-digit variants were matched by exact string, so a handful of
  editorial-erratum ISSNs match nothing — harmless noise, no false positives.
