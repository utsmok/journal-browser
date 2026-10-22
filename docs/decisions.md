# Decisions log

## Settled decisions (with owner sign-off 2026-10-22)

1. **Deal journal lists come from the cOAlition S JCT public dump (CC0), amended with
   openaccess.nl data.** Never scrape the old journal browser; go to the sources.
2. **Stack**: FastAPI + SQLAlchemy 2 (async) + asyncpg on Postgres 17, Next.js,
   docker compose, `uv`.
3. **Ingestion as plain `uv run` jobs** in `backend/jobs/` with a raw landing zone,
   audit rows, and permanent local copies of crucial data.
4. **Clients: `aletheca` (OpenAlex), `aireloom` (OpenAIRE), `stavrophora` (Crossref)**
   — our own bibliofabric family; aletheca is on PyPI and used in depth by
   `ut-metadata` (see `docs/research/aletheca-ut-metadata.md`).
5. **Metrics: collect only.** Register what OpenAlex, scimagojr, and OpenAPC publish.
   No derived substitute metrics in v1.
6. **Institution: University of Twente, ROR `006hf6230`.** v1 is single-institution;
   ROR-keyed schema keeps later multi-institution configuration possible.
7. **Data window: 2020 to now** for all works-derived data.
8. **API budget discipline**: minimize keyed OpenAlex calls; plain entity lookups
   (`W…`/`S…` IDs) need no key. The free key in `~/.zshrc` (`OPENALEX_API_KEY`) is for
   cursor-paged harvests only.
9. **Deployment (PoC)**: private LAN server, straight `docker compose up`; production
   concerns deferred.
10. **Licensing/attribution**: project private for now; no explicit attribution UI yet,
    but every record links to its upstream source and stores a local raw copy.
11. **Frontend styling (2026-10-22)**: openaccess.nl-inspired theme for the initial
    implementation, built on Tailwind v4 CSS variables + shadcn-style components +
    TanStack Query/Table, patterns copied from the TCRC frontend. Re-theming to UT
    branding is a token-block swap (TCRC's audited UT palette is prepared for that).
    Typography: Inter + Montserrat (both SIL OFL, self-hosted via next/font).

## Open questions

1. **Jisc Open Policy Finder API key**: needed for green-OA policy integration
   (`https://api.openpolicyfinder.jisc.ac.uk/retrieve`, `x-api-key` header). Sam will
   request it; integration starts when the key arrives. (Say the word and the harvester
   scaffold is next.)
2. **OpenAPC harvest frequency**: dataset updates are release-based; refresh monthly?
   (default: monthly)
3. **Which OpenAIRE/Crossref fields earn their place**: both are in scope per decision 4,
   but the concrete field selection per entity is open until the harvesters run; the
   `ut-metadata` implementation is the reference.

## Historical notes

- 2026-10-22: initial research phase. An early draft of this project assumed WUR as the
  institution (ROR `04qw24q55`); corrected to Twente (`006hf6230`).
- 2026-10-22: "cited by Twente staff" (two-step W-id batching) demoted to a secondary
  step: scaffold included, full runs wait for an explicit go.
