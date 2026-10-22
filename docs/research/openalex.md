# OpenAlex research — Open Access Journal Browser rebuild

Researched 2026-10-22 (live-verified queries). Docs: help.openalex.org (docs.openalex.org
redirects there; every page has a `<url>.md` raw-markdown form). Data is CC0.

> Note: two API quirks (mailto deprecation, source-filter regression) were newly observed
> the week of research — re-verify before building on them.

## 1. Sources entity (`/sources`)

Resolve a journal by ISSN (print *or* e-ISSN both match; merged via `issn_l`):

    GET /sources?filter=issn:0043-1397
    GET /sources/issn:1944-7973          # single-source by ISSN shortcut (verified)

There is no DOI → source lookup; sources are keyed by ISSN/OpenAlex ID (`S…`).

| Field | Notes |
|---|---|
| `id`, `ids` | `ids`: `openalex`, `issn_l`, `issn` (list), `mag`, `wikidata`, `fatcat` |
| `display_name`, `alternate_titles`, `abbreviated_title` | ISO-4 abbr when known |
| `issn_l`, `issn` | `issn_l` canonical; `has_issn` for presence |
| `type` | `journal`, `conference`, `repository`, `book series`, `ebook platform`, `other`, `metadata` (~206k journals) |
| `host_organization`, `host_organization_name`, `host_organization_lineage` | publisher (P…) entity + hierarchy |
| `is_oa`, `is_in_doaj`, `is_in_doaj_since_year`, `oa_flip_year` | fully-OA flags; DOAJ ≈ 23k, `is_oa` ≈ 65k |
| `is_core` (CWTS/Leiden), `listed_in` | allow-lists; `listed_in` covers many national lists (see `api.openalex.org/source-lists`) |
| `is_ojs`, `is_high_oa_rate`, `is_in_scielo`, `is_preprint_repository` | platform/OA flags |
| `homepage_url`, `societies`, `country_code` | homepage not filterable |
| `apc_prices` [{price,currency}], `apc_usd`, `apc_usd_by_year` | list-price APC from DOAJ + curation; hybrid journals thin |
| `topics`, `topic_share` | ranked topics w/ counts + subfield/field/domain hierarchy (replaces deprecated `concepts`) |
| `works_count`, `cited_by_count`, `oa_works_count` | totals on the source |
| `counts_by_year` | ~10yr+ rollup of works / OA works / citations per year — journal trend charts for free |
| `summary_stats` | **`2yr_mean_citedness`** (IF-like), **`h_index`**, **`i10_index`** — filterable/sortable |

## 2. Journal metrics: native vs. gaps

OpenAlex natively gives `2yr_mean_citedness` (essentially an open IF), `h_index`, `i10_index`,
per-source — plus `cited_by_count`, `works_count`, and `counts_by_year` to derive
CiteScore-style metrics yourself (citations in year *Y* to docs from *Y-1..Y-3* ÷ docs
*Y-1..Y-3*; computable from `counts_by_year` alone). It does **not** have SJR, SNIP,
CiteScore, quartiles, or JCR IF.

Open substitutes:

- **SJR + quartiles**: scimagojr.com `journalrank.php?out=xls` CSV, ISSN-keyed, CC-BY.
- **DOAJ** API (`doaj.org/api/v2/search/journals/issn:…`) for OA licence/APC/keywords
  (endpoint returned 502 on research day — recipe unverified).
- **SNIP/CiteScore/JCR have no open source** — derive lookalikes from OpenAlex or buy Scopus.
- CWTS Core (`is_core:true`) as an open proxy for "selectively indexed".

## 3. Institution publication stats

WUR = `https://ror.org/04qw24q55` → OpenAlex `I913481162`. Works filters do **not** match
ROR URLs (verified: returns 0) — map ROR → I-id once:
`GET /institutions?filter=ror:https://ror.org/04qw24q55`.

    # works per year since 2019
    /works?filter=institutions.id:I913481162,from_publication_date:2019-01-01&group_by=publication_year
    # 2023 OA breakdown (verified: gold 2289, hybrid 1897, green 1492, bronze 212, diamond 186, closed 116 of 6192)
    /works?filter=institutions.id:I913481162,publication_year:2023&group_by=open_access.oa_status
    # corresponding author (approximation; old combined filter now 400s)
    /works?filter=institutions.id:I913481162,authorships.is_corresponding:true,publication_year:2023  # 4796 ✓

`group_by` takes one field per call; returns `{key, key_display_name, count}`, ≤200
groups/page (cursor-paged). Combine with `primary_location.source.id` for per-journal
breakdowns.

## 4. "Cited by [institution] staff" — feasible, in two steps

No direct one-call filter: `cites:S…` / `referenced_works:S…` silently match nothing
(verified → 0); reference filters only accept work IDs. Verified approach:

1. Collect journal X's recent work IDs, `select=id`, `per_page=100`, cursor-paged, bounded
   with `from_publication_date` (5 years → ~3k works for Water Research):
   `/works?filter=primary_location.source.id:S204847658,from_publication_date:2019-01-01&select=id`
2. Batch ≤100 IDs with OR (limit: 100 values/filter) and count:
   `/works?filter=institutions.id:I913481162,referenced_works:W1|W2|…|W100` → sum counts.
   (`referenced_works:W4361000981` verified: 151 hits.)

Store the W-id list per journal (refresh yearly); the count queries are cheap.

## 5. Similar journals

- **Co-cited via staff citations**: for the batches above, swap `select` for a facet:
  `/works?filter=institutions.id:I913481162,referenced_works:W…&group_by=primary_location.source.id`
  (verified). For "journals we publish in *when citing X*", group the citing-works set the
  same way.
- **Topic + community**: find X's topic ids (`topics.id`), then
  `/sources?filter=topics.subfield.id:…,type:journal&sort=summary_stats.2yr_mean_citedness:desc`.
- Or locally: cosine similarity over `topic_share` vectors, weighted by local usage.

## 6. Rates, etiquette, pagination (changed vs. old docs)

- **mailto is dead**: responses now say it "doesn't raise this limit". Keyless = shared
  ~$0.10/day budget per IP, 10 req/s. **Get a free API key** ($1/day, 30 req/s): account at
  openalex.org, or `POST /api-keys {"email":…}` + click emailed link. Send as `api_key=` or
  `Authorization: Bearer`.
- **Cursor paging past page 1 requires a key.** Start `cursor=*`, follow `meta.next_cursor`
  to `null`. Basic paging capped at 10,000 results; `per_page` max 100 (200 deprecated).
- `select=` top-level fields to slim responses (e.g. `select=id,display_name,summary_stats`);
  batch ID lookups with `|` (≤100); expect `429` on budget/per-second — back off; headers
  `X-RateLimit-*` show remaining budget. Heavy patterns (group_by on big sets) cost more
  credits — watch `meta.cost_usd`.

## 7. Client library

`pyalex` (v0.21) is the de-facto OpenAlex client (keyset pagination, filters as kwargs).
`bibliofabric` (v0.5.2, MIT, Py3.12+) is an async httpx *framework for building* scholarly-API
clients (retry/backoff, TTL cache, auth strategies, resource mixins) — its family already has
`aireloom` (OpenAIRE) and `stavrophora` (Crossref) as proof of pattern; an OpenAlex client on
bibliofabric would follow the same shape. Choice is a project decision (see decisions.md).

## 8. Gaps vs. Scopus / old WUR browser

- **Missing metrics**: SJR, SNIP, CiteScore, quartiles, JCR IF — only the open IF-lookalike
  (`2yr_mean_citedness`) and derivable h/i10/CiteScore-style numbers. Join scimagojr CSV by
  ISSN for SJR/quartiles.
- **No curated quality bar** (by design): use `is_in_doaj` / `is_core` / `listed_in` as filters.
- APC = current list price only (hybrid coverage weak); no per-year historical APC.
- "Cited-by-institution" and co-citation facets need the two-step W-id batching (§4).
- Corresponding-author-affiliation filter is only an approximation (§3 caveat).
- OpenAlex citation coverage skews recent/OA vs. Scopus; pre-2012 counts undercount.
