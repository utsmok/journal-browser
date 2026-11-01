# Admin panel

Active contributors: utsmok

## Purpose

The admin panel is the operator's console for everything curated or
configured: editing settings, curating the deal register, reviewing author
identity resolutions, triaging visitor feedback, inspecting harvest runs,
and overriding served docs. The backend surface is the `/api/v1/admin`
router package; the UI is a global panel at `/admin` plus a trimmed
per-institution panel at `/{code}/admin`.

![The global admin panel: harvest runs, feedback triage, deal curation](images/web-admin-panel.png)

## Key abstractions

| Abstraction | Where | Role |
|---|---|---|
| Admin token | `backend/src/journal_browser/routers/admin/auth.py` | Stateless HMAC bearer token exchanged for the admin password |
| `AdminDep` | `backend/src/journal_browser/routers/admin/auth.py` | Dependency that guards every admin endpoint |
| Settings registry | `backend/src/journal_browser/settings_schema.py` | One field definition per editable knob, sectioned global vs institution |
| Manual override | `backend/src/journal_browser/models/app_data.py` (`ManualOverride`) | Curated values that re-applied harvests must never overwrite |
| Identity ledger | `backend/src/journal_browser/models/openalex.py` (`AuthorIdentity`) | One row per proposed external author identity with its review status |
| Doc edit | `backend/src/journal_browser/models/app_data.py` (`DocEdit`) | Per-block replacement for a served markdown doc, stored without touching source files |

## How it works

### Auth model

The password comes from the `admin_password` setting (`JB_ADMIN_PASSWORD`).
When it is empty the panel is disabled: `POST /api/v1/admin/login` and every
guarded endpoint return 403 with `admin disabled: set JB_ADMIN_PASSWORD`.

`POST /api/v1/admin/login` compares the submitted password with
`hmac.compare_digest` and issues a token of the form `{expires}.{mac}`,
where `mac` is an HMAC-SHA256 over the expiry timestamp keyed by
`sha256("jb-admin:" + password)`. The token is stateless, valid for 12
hours, and needs no server-side session. Because the MAC secret derives
from the current password, changing the password in the panel invalidates
all old tokens immediately. Every admin endpoint depends on `AdminDep`,
which returns 401 for a missing, expired, or invalid token.

### Harvest runs and flagged deals

`backend/src/journal_browser/routers/admin/runs.py` serves two read-only
endpoints:

- `GET /admin/runs`: recent harvest runs, newest first, with the source,
  entity type, status, timestamps, and stats JSON. An optional
  `institution` query filter narrows to one university; rows with no
  institution render as "shared" (global jobs). See
  [Data pipeline](../systems/data-pipeline/index.md) for how the runs are
  produced.
- `GET /admin/flagged`: deals with `needs_curation = true`, with the
  harvester's reason string.

### Settings editing

`backend/src/journal_browser/routers/admin/settings_admin.py` exposes
`GET /admin/settings` (the full field schema plus the values of the global
section) and `PUT /admin/settings`. Secrets arrive masked as `********`;
the client panel never echoes a stored secret. A PUT that sends an empty
string or the mask for a secret keeps the current value, so rendering a
form without retyping a key cannot wipe it. Writes go to
`backend/settings.yaml`, which overrides `.env` values and reloads live:
the writer truncates and rewrites in place (a compose bind mount cannot
replace a mount point via rename), then resets the settings cache.
`ignored_issns` values are normalized to `XXXX-XXXX` ISSN-L form on write.

Institution-scoped configuration is a separate endpoint,
`GET/PUT /admin/institutions/{code}`, editing the row described in
[Multi-institution core](multi-institution.md). The PUT is PATCH-shaped:
absent fields stay untouched, explicit nulls clear nullable columns, and
nulls on `name`, `data_window_start`, `data_window_end`, or `active` are
rejected.

### Deal curation

`backend/src/journal_browser/routers/admin/deals_admin.py` is the curation
CRUD over the shared deal register. Two invariants shape it:

- **Edits stick.** Every accepted field edit upserts a `manual_overrides`
  row (`table_name="deals"`, `row_key` = deal id, one row per changed
  field). The harvest-side `apply_overrides` re-applies these after each
  harvester upsert, so curated values survive every re-harvest.
- **Removals are flags, not deletions.** Removing a journal from a deal
  sets `excluded = true` on the `deal_journals` row because a deleted row
  would be re-inserted by the next JCT harvest. Removing a participation
  writes a tombstone override on `deal_institutions` for the same reason;
  re-adding the institution deletes the tombstone.

Other behaviors worth knowing:

- A human edit clears `needs_curation` and its reason and pins
  `last_reviewed` to today, marking the deal as reviewed.
- Creation accepts an existing `publisher_id` or a new `publisher_name`;
  a duplicate `esac_id` returns 409.
- Journal adds resolve ISSNs through the ISSN-L index and upsert with
  `source="manual"`.
- After any mutation the handler schedules a search-flags refresh through
  `backend/src/journal_browser/services/flags_refresh.py`, so coverage
  facets update without a full harvest.

### Author identity review

`backend/src/journal_browser/routers/admin/authors_admin.py` exposes
`GET /admin/author-identities` (filter by status or institution, newest
activity first, with the local author's display name joined in) and
`PUT /admin/author-identities` (flip one row's status; the full primary key
travels in the request body).

The rows come from the author-id cascade in
`backend/src/journal_browser/harvest/author_ids.py`, which resolves each
local Pure author to OpenAlex ids and writes a ledger entry per candidate
binding with a status of `confirmed`, `candidate`, or `rejected`.
Candidates never auto-promote; ambiguous namesake bindings land in this
queue for human review.

The fragmentation-twin ledger gate is the one place the cascade confirms
without a human: an alternate OpenAlex id rides along as a confirmed
"fragmentation twin" only when the work-level evidence says it is the same
human. It must never co-occur with the primary id on one authorship list,
and the ORCID evidence across primary and alternates must name at most one
human. An alternate that fails either test is a competing namesake and
stays a candidate here.

Decisions are sticky across re-runs: the cascade's upsert only updates
candidate rows (a SQL CASE leaves `confirmed` and `rejected` untouched), so
a rejection blocks re-proposal of that id and a confirmation keeps it. The
authors ingest reads the ledger additively: confirmed rows feed
`authors.openalex_ids` at the next authors ingest; rejected rows stay out.

### Feedback triage

`backend/src/journal_browser/routers/admin/feedback_admin.py` lists reports
(`GET /admin/feedback`, optional `status` filter), patches status,
priority, and resolution notes (`PATCH /admin/feedback/{id}`), and deletes
reports. The full loop, including what visitors submit, is covered in
[Feedback](feedback.md).

### Docs editing

`backend/src/journal_browser/routers/admin/docs_admin.py` stores per-block
replacements for the served markdown docs: `PUT /admin/docs/{slug}/edits`
saves one block's replacement, `DELETE /admin/docs/{slug}/edits/{block_key}`
reverts it. Edits live in the `doc_edits` table and are applied at read
time by `backend/src/journal_browser/routers/docs.py`, so the source files
in `docs/` stay untouched. `original_hash` records what the editor saw;
it is provenance only and is never verified on write.

## How the UI talks to the API

`frontend/lib/admin.ts` is the shared plumbing:

- The token lives in `sessionStorage` under `jb-admin-token`, managed by
  the `useAdminToken` hook.
- `adminGet`, `adminPut`, `adminPost`, `adminPatch`, and `adminDelete` wrap
  `fetch` with the bearer header, no caching, and an `AdminError` carrying
  the HTTP status and path. Any 401 clears the stored token and drops the
  user back to the login form.
- Payload types are derived from the generated contract in
  `frontend/lib/api-types.ts` rather than hand-written, so the UI tracks
  the OpenAPI schema (see the type pipeline in
  [Backend](../apps/backend/index.md)).

The panels:

- `frontend/app/admin/page.tsx` is the global panel: harvest runs with an
  institution filter, the feedback triage table, the deals table with the
  inline editor and create form, flagged deals (a row click opens the
  editor), the institution settings picker, and the global settings form.
- `frontend/app/[inst]/admin/page.tsx` is the per-institution panel: this
  university's runs and its institution settings form.
- Shared widgets live in `frontend/components/admin/`: `login-form.tsx`,
  `runs-table.tsx`, `settings-forms.tsx`, `deal-editor.tsx`, and
  `feedback-table.tsx`.
- Docs editing is not a panel section; an edit toolbar appears inline on
  the public docs pages (`frontend/app/[inst]/docs/[slug]/page.tsx`) for a
  signed-in admin.

## Integration points

- Settings writes feed the settings system described in
  [Backend configuration](../apps/backend/configuration.md).
- Deal mutations schedule the search-flags refresh and rely on the
  override replay in the harvest pipeline; see
  [Data pipeline](../systems/data-pipeline/index.md).
- Identity decisions change author listings only at the next authors
  ingest.
- Feedback triage closes the loop started by the public widget; see
  [Feedback](feedback.md).

## Entry points for modification

- Add a global setting: add the field to `Settings` in
  `backend/src/journal_browser/config.py` and a registry entry in
  `backend/src/journal_browser/settings_schema.py`; the admin forms render
  whatever the schema declares. Regenerate the API types afterwards.
- Add an admin area: create a submodule under
  `backend/src/journal_browser/routers/admin/` that carries its own
  `/admin` prefix, and add it to the include list in
  `backend/src/journal_browser/routers/admin/__init__.py` (include order
  mirrors the route snapshot). Regenerate
  `frontend/lib/api-types.ts`.
- Add a curated deal field: extend `DealUpdate` and `_deal_payload` in
  `backend/src/journal_browser/routers/admin/deals_admin.py` so the field
  round-trips through the override ledger.
- Change token lifetime or secret derivation: `backend/src/journal_browser/routers/admin/auth.py`
  (both are local to that module).

## Key source files

| File | Contents |
|---|---|
| `backend/src/journal_browser/routers/admin/__init__.py` | Router assembly and include order |
| `backend/src/journal_browser/routers/admin/auth.py` | Login, token issue/verify, `AdminDep` |
| `backend/src/journal_browser/routers/admin/runs.py` | Run list and flagged deals |
| `backend/src/journal_browser/routers/admin/settings_admin.py` | Settings and institution-row editing |
| `backend/src/journal_browser/routers/admin/deals_admin.py` | Deal curation CRUD and override ledger writes |
| `backend/src/journal_browser/routers/admin/authors_admin.py` | Identity review list and status flips |
| `backend/src/journal_browser/routers/admin/feedback_admin.py` | Feedback triage endpoints |
| `backend/src/journal_browser/routers/admin/docs_admin.py` | Doc block edits |
| `backend/src/journal_browser/harvest/author_ids.py` | The cascade that feeds the identity ledger |
| `backend/src/journal_browser/services/flags_refresh.py` | Post-edit search-flag refresh |
| `frontend/lib/admin.ts` | Token storage, authenticated fetch helpers, admin types |
| `frontend/app/admin/page.tsx` | Global admin panel |
| `frontend/app/[inst]/admin/page.tsx` | Per-institution admin panel |
| `frontend/components/admin/` | Login form, runs table, settings forms, deal editor, feedback table |
