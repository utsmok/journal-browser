---
name: qa-web
description: >
  QA tests for the journal-browser Next.js frontend. Functional browser testing
  of the institution-scoped public site (search, facets, detail pages, deals,
  docs, feedback) and the admin panel, via droid-control agent-browser.
---

# Web QA (Next.js frontend)

The frontend is an App Router app under `frontend/app/[inst]/` plus a global
admin at `frontend/app/admin/`. All flows run against the QA backend on port
8100 through the dev server's `/api` proxy.

## Testing target

No preview deployments exist for this project. Test the branch's actual code
by running the dev server locally (Strategy 2). Never fall back to the live
deployment on ports 3000/8000 -- it runs different code and writes to the
production database.

Pre-requisites: the QA backend from `qa-backend/SKILL.md` must already be up
on `127.0.0.1:8100` (health check first), and `npm ci` must have run in
`frontend/`.

Boot (from repo root):

```bash
cd frontend && API_PROXY_URL=http://127.0.0.1:8100 npm run dev -- -p 3100
```

Poll `http://127.0.0.1:3100` until it responds.

Hard rules:

- `API_PROXY_URL` is NOT optional. Without it `frontend/next.config.mjs`
  proxies `/api/*` to `http://localhost:8000` -- the LIVE backend. Any flow
  run without the proxy env var may have hit production; if that happened,
  report the run as an incident (live feedback POSTs or admin logins are the
  dangerous ones).
- Never bind port 3000 (live frontend) or 8000 (live backend).
- Invoke the `droid-control` skill before any browser interaction. Use its
  agent-browser route, its Capture atom for screenshots, and its Verify
  stage for assertions.

## Personas

- **visitor:** no login. Exercises the whole public site and the feedback
  widget.
- **admin:** open `/admin`, submit the password from `QA_ADMIN_PASSWORD`,
  and verify the app stores the returned bearer token and renders the admin
  sections. Logging out (401 handling) should clear the token.

## Flow menu (pick by diff; not a checklist)

**Public site (visitor)** -- base URL `http://127.0.0.1:3100`
1. Landing redirect: with one active institution, `/` lands on the `ut` site
   (the root page redirects or the chooser shows -- assert whichever the
   current code does, per `frontend/app/page.tsx`).
2. Header/site meta: institution name, library link, and support email come
   from `/meta`; the first paint already names Twente (server-rendered env
   seed).
3. Journal search: type in the home search box (it is debounced ~350 ms),
   results table renders the fixture journals; run a query like "hydrology".
4. Search scopes: switch scope (all/title/publisher/topic) and verify result
   sets change plausibly.
5. Filters: open the filter panel, toggle an OA-type or quartile facet, and
   verify the result set and the URL query state update together (URL is the
   state).
6. Pagination: advance to the next page and verify the cursor lands in the
   URL and rows change.
7. Semantic toggle: switch to "match by meaning", search "water modelling",
   and verify the water journals appear in the results. Do NOT assert a
   specific ranking: the query is embedded by the real model while the
   fixture vectors are synthetic, so ordering is not meaningful.
8. Journal detail: open the gold fixture journal (`1111-1111`) from results;
   the page shows APC cost, quartile, OA-type badge (gold), deal coverage,
   and the similar-journals list (hydro-adjacent fixtures).
9. Author/publisher/orgunit pages: navigate from a journal or direct URL;
   pages render without error (fixture data is thin -- empty sections are
   fine, error boundaries are not).
10. Deals register: open `/ut/deals`, verify the fixture deal renders with
    journal count; open its detail page and the covered journal list.
11. Docs viewer: open the docs route, pick a document, verify markdown
    blocks render (with `JB_DOCS_DIR` unset the backend serves the repo's
    `docs/` directory, so the list is non-empty on a repo boot; empty is
    acceptable only when `JB_DOCS_DIR` points at an empty directory).
12. Feedback widget: submit feedback with a title and description as a
    visitor; verify the success state. This writes the QA database only
    (verify the proxy target first -- see hard rules).
13. Theme toggle: cycle the theme; verify `document.documentElement` class /
    color tokens change and persist visually across a screenshot pair.

**Admin panel (admin persona)** -- `http://127.0.0.1:3100/admin`
14. Login: wrong password shows an error; correct password enters the panel
    (bearer token in sessionStorage).
15. Settings: global settings form renders; secrets show masked; editing a
    display field saves via PUT (writes the isolated `/tmp/qa-settings.yaml`).
16. Deals curation: the fixture deal opens in the editor; a display-field
    edit saves (epoch invalidation triggers a refetch).
17. Deal create round trip: create a minimal deal in the admin panel's
    create form; verify it appears in the public `/ut/deals` register (the
    backend author-identities endpoints exist but have no admin UI -- do
    not look for one).
18. Feedback triage: the flow-12 submission appears; change its status and
    verify the row updates.
19. Runs: the harvest-runs table renders (fixture DB: empty is valid).

## Per-persona variations

- Visitor negative: navigating directly to `/admin` without a token shows
  the login gate, and no admin data renders.
- Admin negative: after clearing the token from sessionStorage, any admin
  API call 401s and the app signs out to the login gate.

## Error handling and edge cases

- The dev server compiles routes lazily; the first hit on a route can take
  seconds. Wait for compilation before calling it a failure.
- Fixture ISSNs are fake; do not expect external journal imagery or ISSN
  resolution anywhere.
- The home page is large and client-hydrated; prefer accessibility-tree
  text snapshots for assertions and screenshots only as supplementary proof.

## Known failure modes

1. **Proxy pointed at live.** Booting the dev server without
   `API_PROXY_URL=http://127.0.0.1:8100` silently proxies `/api` to the
   live backend on port 8000. Always verify the booted process env or probe
   a QA-only endpoint before testing (e.g., confirm the fixture deal
   `qa-fixture-deal` appears; if the real deal register shows instead, stop
   and report).
2. **Port collisions with live.** 3000/8000 are the live stack; 3100/8100
   are QA-owned. A stale QA dev server on 3100 can be killed and restarted.
3. **Admin login succeeds against the wrong backend.** Symptom of failure
   mode 1: the admin panel loads real deals. Same check as above.
4. **Debounced search looks broken.** The search box debounces ~350 ms; a
   snapshot taken immediately after typing shows stale results. Wait past
   the debounce.
5. **First semantic search hangs.** The ONNX model loads on first use in the
   backend; allow a generous timeout.
6. **First-paint institution name.** The root layout seeds from env at
   server start; changing institution env requires a dev-server restart to
   observe.
