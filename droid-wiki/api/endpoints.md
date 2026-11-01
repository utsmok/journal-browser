# Endpoints

The catalog below covers all 42 operations in the committed `openapi.json`,
grouped by family. Paths are shown relative to the `/api/v1` base; the
machine-readable schema at `openapi.json` remains the source of truth for
parameters and response shapes, and
[API surface](../apps/backend/api-surface.md) explains how the families are
organized.

Conventions across the catalog:

- `{code}` is the institution code (`ut`, `rug`); a request to an unknown
  code returns 404.
- Admin endpoints require the HMAC bearer token obtained from
  `POST /admin/login` (12 hour lifetime; changing the admin password
  invalidates outstanding tokens).
- Search endpoints take `q`, filter facets, `sort`/`dir`, and either a
  `cursor` (journals) or `offset` (authors, publishers, orgunits); pass
  `include_facets` to get filter counts with the page.

## Institutions

| Method | Path | Purpose |
|---|---|---|
| GET | `/institutions` | List hosted institutions with codes, display identity, and data windows, for the landing page |

## Admin

| Method | Path | Purpose |
|---|---|---|
| POST | `/admin/login` | Exchange the admin password for a stateless bearer token |
| GET | `/admin/runs` | List harvest runs (latest, with `limit`), filterable by institution |
| GET | `/admin/flagged` | List deals flagged `needs_curation` for review |
| GET | `/admin/settings` | Show effective settings with sources and masked secrets |
| PUT | `/admin/settings` | Write settings to the live overlay |
| GET | `/admin/institutions/{code}` | Inspect one institution row |
| PUT | `/admin/institutions/{code}` | Edit an institution's identity, links, and data window |
| GET | `/admin/deals` | List all deals for curation |
| POST | `/admin/deals` | Create a manual deal (for example the Emerald contract) |
| GET | `/admin/deals/{deal_id}` | Show one deal |
| PUT | `/admin/deals/{deal_id}` | Update deal fields |
| PUT | `/admin/deals/{deal_id}/journals` | Replace the deal's journal membership |
| PUT | `/admin/deals/{deal_id}/participations` | Replace which institutions participate |
| GET | `/admin/feedback` | List feedback for triage, filterable by `status` |
| PATCH | `/admin/feedback/{feedback_id}` | Update triage status |
| DELETE | `/admin/feedback/{feedback_id}` | Delete a feedback item |
| PUT | `/admin/docs/{slug}/edits` | Save a block-level text override for a doc |
| DELETE | `/admin/docs/{slug}/edits/{block_key}` | Remove an override, restoring source text |
| GET | `/admin/author-identities` | List author identity candidates for review, filterable by `status` and institution |
| PUT | `/admin/author-identities` | Accept or reject an identity candidate |

## Feedback

| Method | Path | Purpose |
|---|---|---|
| POST | `/feedback` | Anonymous intake from the in-app feedback widget |

## Docs

| Method | Path | Purpose |
|---|---|---|
| GET | `/docs` | Index the served markdown documents, with edit counts |
| GET | `/docs/{slug}` | Return one document as keyed blocks with admin overrides applied |

## Health

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` | Database `SELECT 1` plus the application version |

## Institution-scoped: journals

| Method | Path | Purpose |
|---|---|---|
| GET | `/{code}/journals` | Filtered, faceted journal search with cursor pagination |
| GET | `/{code}/journals/semantic-search` | Embedding-based journal search for a natural-language `q` |
| GET | `/{code}/journals/{issn_l}/similar` | Similar journals from the embedding space |
| GET | `/{code}/journals/{issn_l}/works` | Paged works published in the journal |
| GET | `/{code}/journals/{issn_l}` | Full journal detail bundle with per-field attribution |

## Institution-scoped: authors

| Method | Path | Purpose |
|---|---|---|
| GET | `/{code}/authors` | Author search with org-tree (`faculty`, `org`) and works filters |
| GET | `/{code}/authors/{pure_uuid}` | Author profile with works and deal usage |

## Institution-scoped: publishers

| Method | Path | Purpose |
|---|---|---|
| GET | `/{code}/publishers` | Publisher search with the same filter facets as journals |
| GET | `/{code}/publishers/{name}` | Publisher detail with its journals and deals |

## Institution-scoped: orgunits

| Method | Path | Purpose |
|---|---|---|
| GET | `/{code}/orgunits` | Organizational unit search by level, faculty, and works count |
| GET | `/{code}/orgunits/faculty/{name}` | Faculty page: groups, journal usage, deal coverage |
| GET | `/{code}/orgunits/group/{name}` | Research group page |
| GET | `/{code}/orgunits/institute/{name}` | Institute page |

## Institution-scoped: deals

| Method | Path | Purpose |
|---|---|---|
| GET | `/{code}/deals` | Open-access agreements for the institution, filterable by `status` |
| GET | `/{code}/deals/{deal_id}` | Deal detail with covered journals |

## Institution-scoped: meta

| Method | Path | Purpose |
|---|---|---|
| GET | `/{code}/meta/limitations` | Data-limitation registry entries, filterable by `source` |
| GET | `/{code}/meta/freshness` | Data freshness per source plus the institution's display identity |
