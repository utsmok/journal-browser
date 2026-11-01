# Feedback

Active contributors: utsmok

## Purpose

The feedback loop lets visitors report problems without an account: a
floating button on every page opens a short form, the report lands in the
database with the page's own data attached, and the operator triages it in
the admin panel. The site has no user accounts, so intake is anonymous by
design.

## Key abstractions

| Abstraction | Where | Role |
|---|---|---|
| Intake endpoint | `backend/src/journal_browser/routers/feedback.py` | Unauthenticated `POST /api/v1/feedback` |
| Feedback row | `backend/src/journal_browser/models/app_data.py` (`Feedback`, table `feedback_items`) | Stored report with status, priority, category, and the page-data dump |
| Page-data dump | `frontend/components/feedback/feedback-widget.tsx` (`buildPageDump`) | Snapshot of the TanStack Query cache live on the page at submit time |
| Triage API | `backend/src/journal_browser/routers/admin/feedback_admin.py` | List, patch, and delete for signed-in admins |
| Triage UI | `frontend/components/admin/feedback-table.tsx` | The admin panel's feedback section |
| Category vocabulary | `backend/src/journal_browser/vocab.py` (`FeedbackCategory`) | The accepted category set validated at the API |

## How it works

### What visitors can report

The widget mounts once in `frontend/app/layout.tsx`, so the button is
available on every page. The form asks for:

- A short title, required, at most 255 characters.
- A description of what happened and what was expected, required, at most
  8000 characters.
- An optional category: bug, wrong data, feature request, improvement, or
  other (mapped to `FeedbackCategory` in
  `backend/src/journal_browser/vocab.py`).

Two things attach automatically, and the form says so:

- `page_url`: the current pathname.
- `page_data`: the dump described next.

### Where it lands

`POST /api/v1/feedback` validates the payload and inserts one
`feedback_items` row. New rows start with status `todo` and priority
`normal` (the columns' server defaults). The table constrains status to
`todo | in_progress | done | wontfix`, priority to
`low | normal | high | critical`, and category to the five API values.

The page-data dump is the distinctive part. `buildPageDump` walks the
TanStack Query cache, keeps every entry that has data (most recently
updated first), and records each entry's query key, update timestamp, and
data payload, plus the page URL, user agent, viewport, submit time, and a
count of entries skipped as oversize. The client caps the dump at about
700 KB so the current page's responses stay in; the server rejects
anything over 1 MB with 413. A "wrong data" report therefore arrives with
the exact API responses the reporter saw, which makes most reports
reproducible without asking the visitor for details.

`backend/tests/test_feedback.py` covers intake with dump storage, the
category and size rejections, the token requirement on triage endpoints,
and the patch/filter/delete flows.

### The admin triage flow

The Feedback section of the global admin panel (see
[Admin panel](admin.md)) lists reports newest first with a status filter.
Per report the operator can:

- Set the status inline with a select: `todo`, `in_progress`, `done`, or
  `wontfix`.
- Set the priority inline: `low`, `normal`, `high`, or `critical`.
- Expand the row to read the full description, the report's page URL, the
  page-data dump as formatted JSON (with the count of cached responses),
  write resolution notes, or delete the report.

These map one-to-one onto `GET /api/v1/admin/feedback`,
`PATCH /api/v1/admin/feedback/{id}`, and
`DELETE /api/v1/admin/feedback/{id}`, all guarded by the admin token.
Triage is manual throughout: nothing re-opens, escalates, or resolves a
report automatically, and there is no visitor-facing follow-up because
reports carry no return address.

### Connection to the limitations registry

There is none, and that is worth stating plainly. The limitations registry
(the `Limitation` table in `backend/src/journal_browser/models/app_data.py`,
served by `backend/src/journal_browser/routers/meta.py` at
`/{code}/meta/limitations`) lists known data caveats that the UI surfaces
proactively. A feedback report categorized as "data" may describe a caveat
that is already registered, but the two tables share no key and no join:
linking a report to a registered limitation, or promoting a recurring
report into a new `Limitation` entry, is a judgment the operator makes
during triage.

## Integration points

- The widget needs no configuration and appears on all pages, including
  global surfaces.
- The triage section is embedded in the global admin panel; see
  [Admin panel](admin.md).
- The `feedback_items` table is described with the other application
  tables on [Data model](../systems/data-model.md).

## Entry points for modification

- Add a category: extend `FeedbackCategory` in
  `backend/src/journal_browser/vocab.py`, the widget's `CATEGORIES` list in
  `frontend/components/feedback/feedback-widget.tsx`, and the
  `ck_feedback_items_category` check constraint through a migration.
- Attach more context to reports: extend `buildPageDump` in
  `frontend/components/feedback/feedback-widget.tsx`; the payload is a
  free-form JSONB object, so no backend change is required for additive
  fields.
- Change triage vocabulary or defaults: the status and priority sets are
  constrained in `backend/src/journal_browser/models/app_data.py` and
  mirrored in `backend/src/journal_browser/vocab.py` and the admin table
  component.

## Key source files

| File | Contents |
|---|---|
| `backend/src/journal_browser/routers/feedback.py` | Public intake endpoint |
| `backend/src/journal_browser/models/app_data.py` | `Feedback` (and `Limitation`) models |
| `backend/src/journal_browser/vocab.py` | `FeedbackCategory`, `FeedbackStatus`, `FeedbackPriority` |
| `backend/src/journal_browser/routers/admin/feedback_admin.py` | Triage endpoints |
| `backend/tests/test_feedback.py` | Intake and triage tests |
| `frontend/components/feedback/feedback-widget.tsx` | Widget form and page-data dump |
| `frontend/app/layout.tsx` | Where the widget mounts |
| `frontend/components/admin/feedback-table.tsx` | Admin triage table |
