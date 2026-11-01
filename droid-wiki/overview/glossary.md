# Glossary

Terms used across the codebase and this wiki.

| Term | Meaning |
|---|---|
| **APC** | Article processing charge; the fee a journal charges to publish open access. Aggregated per journal from OpenAPC into `journal_apc_aggregates` and `journals.latest_apc_euro`. |
| **Bootstrap** | The one-shot compose service that runs `backend/jobs/bootstrap.py`: migrations + the harvest DAG on a fresh database. |
| **CERIF** | The Common European Research Information Format; the entity model behind Pure's OAI feed (orgunits, persons, publications). |
| **Cache epoch** | Invalidation counter in `backend/src/journal_browser/services/cache.py`; harvest bumps bump the epoch so facet/query caches rebuild. |
| **Diamond OA** | Open access without APCs. Assigned when DOAJ-listed with no APC signal. One of five `oa_type` values. |
| **DOAJ** | Directory of Open Access Journals; the canonical source for gold/diamond OA status (`doaj_in_doaj`, `doaj_has_apc` journal flags). |
| **Deal register** | The institution's open-access agreements, harvested from openaccess.nl (canonical) and enriched from the JCT ESAC dump. |
| **ESAC / JCT** | ESAC ids and journal lists from the cOAlition S journal contract tool; enrichment only — absence is never evidence a deal does not exist. |
| **FTS** | Postgres full-text search; drives journal search alongside facets. |
| **Generic OA** | The `oa_type` bucket for OA evidence without an APC signal; replaced an overeager diamond assignment. |
| **HNSW** | The pgvector index type on `journals.embedding`; approximate nearest-neighbor for semantic search. |
| **Institution code** | The URL path segment (`ut`, `rug`) that scopes every per-institution surface; a row in the `institutions` table. |
| **ISSN-L** | The linking ISSN that merges a journal's print/electronic ISSNs; the key for `journals` and `issn_map`. |
| **Limitations registry** | The `limitations` table of data caveats cited on detail pages. |
| **`needs_curation`** | State on deals/deal journals whose inputs conflicted or had unresolvable ISSNs; surfaced in the admin for manual fixes. |
| **OAI-PMH** | Open Archives Initiative protocol; how the Pure harvest pulls publication records with resumptionToken pagination. |
| **OA color** | Observed OA status sampled from OpenAlex (`journals.oa_status_observed`); distinct from the stored work-level `oa_status`. |
| **oa_type** | Journal-level OA classification derived at query time: gold, diamond, hybrid, generic, subscription. Never stored. |
| **OpenAlex** | The scholarly graph API that supplies the journal universe, institution stats, and works data, via the `aletheca` client. |
| **OpenAIRE** | The EU graph whose DOI matches confirm local work identities, via the `aireloom` client. |
| **Pure** | Elsevier's research information system (`ris.utwente.nl`); the canonical "what has this institute published" source, harvested over OAI-PMH. |
| **Quartile** | SJR quartile from Scimago (`scimagojr_metrics`, `journals.latest_quartile`). |
| **ROR** | Research Organization Registry id; identifies the institution (Twente is `006hf6230`). |
| **`work_identity`** | Confirmed external identifiers (OpenAIRE/OpenAlex/Crossref DOIs) attached to a local work, with candidate rows for review. |
| **Works window** | The publication-year range an institution harvests (`data_window_start`/`end` per institution; UT is 2010 to open). |
| **Author cascade** | The identity-resolution ladder in `backend/src/journal_browser/harvest/author_ids.py`: orcid-exact → name-exact → initials → family → fuzzy, gated by org-tree affiliation. |
| **Landing zone** | `backend/landing/`; verbatim raw responses and job logs survive container rebuilds there. |
