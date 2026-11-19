# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary user: a researcher (author) at a Dutch or international institute
deciding where to submit their next article. They want to know which journals
their institution has open access deals with, what publishing in a journal
costs, how their institution has published there before, and what the journal
covers.

Secondary audience: staff at any institute who deploy and operate their own
instance (setup via `.env` + `docker compose up` + one-shot `bootstrap`).
Admins manage institutions, deals, runs, feedback, and settings in the
`/admin` panel.

## Product Purpose

A public search tool that helps researchers find the best home for their next
article: open access deal coverage, publication costs (APC evidence),
institutional publication statistics, and journal information (quartiles,
scope, publishers, funders). It replaces the WUR-hosted Open Access Journal
Browser (https://library.wur.nl/WebQuery/utbrowser) using only openly
available data. Success means a researcher can answer "where should I
publish?" without asking the library.

## Positioning

Open data and open code are the core unique selling point. Every data layer
(journals, NL deal register, APC evidence, quartiles, embeddings) comes from
open sources, and the code is Apache-2.0 on GitHub
(https://github.com/utsmok/journal-browser). Any institute can run its own
instance; one deployment serves several universities at `/{code}` paths with
a landing chooser at `/`, and shared layers are stored once. Commercial or
institution-locked journal finders cannot truthfully copy either claim.

## Operating Context

- Deployed via Docker Compose on the media VM (192.168.2.153); the live
  instance runs at journalbrowser.samuelmok.cc (frontend published on
  3001, backend on 127.0.0.1:8001).
- Data arrives through an idempotent harvest pipeline (`bootstrap.py`):
  shared global steps once, then per-institution steps (repository harvest,
  enrichment, OpenAIRE, statistics, participation).
- Institutions are configured via `JB_*` env vars and a per-institution
  directory row; every UI label follows the configured institution.
- Anonymous usage tracking (no cookies, no accounts, localStorage session
  id) is opt-out via `JB_ENABLE_USAGE_TRACKING=false`.

## Capabilities and Constraints

- Surfaces: institution chooser (`/`), search + journal browse
  (`/{inst}`), journal pages, author, org unit, publisher, funder pages,
  deals overview, docs, about, admin panel.
- No accounts and no cookies; only a localStorage session id that rotates
  after 30 idle minutes.
- Raw IPs are nulled after a retention window; countries and events stay.
- Explicitly undecided: none recorded.

## Brand Commitments

- Name: **Open Journal Browser**, abbreviated **OJB**. The name is
  deliberately generic, like the incumbent tool it improves on.
- Core message to keep visible: open data and open code.
- Logo assets (2026-11-05): wordmark and monogram SVGs live at
  `frontend/public/ojb-wordmark.svg` and `frontend/public/obj-monogram.svg`
  (the monogram filename keeps its original "obj" spelling). Theme-aware
  React versions are in `frontend/components/logo.tsx`; the monogram is the
  favicon (`frontend/app/icon.svg`). Brand letters are fixed cyan `#00d7f0`
  and signal orange `#f06e00`; neutral letters use `currentColor`.
- Rename scope decision (2026-11-04): the rename applies to UI copy and
  docs only. The repo name (`utsmok/journal-browser`), npm package names,
  and the journalbrowser.samuelmok.cc domain stay unchanged, so GitHub
  links in the footer and about page remain valid.

## Evidence on Hand

- Real harvested data: OpenAlex journal and works records, the NL open
  access deal register, APC evidence, journal quartiles, embeddings. A live
  deployment serves real institutions (e.g. `/ut`).
- No testimonials, press, or marketing assets exist. Future work must not
  fabricate any.

## Product Principles

- Open by default: open data sources and open code, so every number in the
  UI is verifiable.
- Institution-aware: one codebase serves many institutes, and labels,
  links, and statistics always reflect the configured institution.
- Decision-first: every surface exists to help the researcher choose where
  to publish.
- Privacy-respecting by construction: anonymous usage, no cookies, no
  accounts, explicit opt-out.
