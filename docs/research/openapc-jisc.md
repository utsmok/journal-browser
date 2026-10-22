# Research: OpenAPC and Jisc Open Policy Finder

Checked 2026-10-22, live.

## OpenAPC (github.com/OpenAPC/openapc-de, ODbL)

Release-based datasets of article-level open access costs. Access: raw CSV on GitHub,
an OLAP cube API (`olap.openapc.net/cube/.../aggregate`), and a DOI per release.

Key files:

- `data/apc_de.csv` (~269k rows): `institution, period, euro, doi, is_hybrid, publisher,
  journal_full_title, issn, issn_print, issn_electronic, issn_l, license_ref,
  indexed_in_crossref, pmid, pmcid, ut, url, doaj`. The `ut` column is a Web of Science
  unique article ID (e.g. `ut:000209528900045`), not University of Twente.
  **No Twente rows in this file.**
- `data/transformative_agreements/transformative_agreements.csv` (~267k rows): same
  schema plus `opt_out, agreement, group_id`. **Contains 297 "University of Twente"
  rows** (verified; 2015+), and rows for other Dutch institutions.
- `data/transformative_agreements/contracts.csv`: contract metadata keyed by the TA
  dataset.
- `data/additional_costs.csv`, `data/bpc.csv`: extra cost types (page charges; books).

Use in this project: per-article evidence of "published under agreement X in journal Y
in year Z at cost C" for Twente (deal-coverage validation and actual APC spend), joined
by DOI/ISSN-L. Join key note: `agreement`/`group_id` link to contracts.csv.

## Jisc Open Policy Finder (successor of Sherpa Romeo)

Developer API, requires a key (Sam will request one):

- Endpoint: `https://api.openpolicyfinder.jisc.ac.uk/retrieve`
- Auth: `x-api-key` request header
- Paging: `limit`/`offset`; use `search_after` beyond 10k records
- Filtering: `filter=[["country","equals","ca"]]` style
- Schema: the Sherpa JSON schema (`system_metadata` with id/date_created/date_modified/
  uri; `_phrases` suffix pattern for discrete values; English only)

Item types include `publication`, `publisher` (others to be enumerated once a key is
available). This replaces both the Sherpa v2 feed and the WUR proxy
(`open_policy_finder.php`) the old browser used for green-OA display.
