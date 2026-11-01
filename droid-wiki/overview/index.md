# Journal Browser overview

Journal Browser is a public search tool that helps researchers find where to
publish. It shows which journals are covered by open-access deals, what
publishing in them costs, how their institution uses those journals, and what
the journals are about. It replaces the WUR-hosted [Open Access Journal
Browser](https://library.wur.nl/WebQuery/utbrowser) and runs on openly
available data only.

![Journal Browser — institution home with search, facets, and results](images/web-home.png)

## What it does

- **Journal search and browse** — full-text search with filters (OA type,
  quartile, deal coverage, publisher) plus semantic "match by meaning"
  search over journal embeddings. See [Search and discovery](../systems/search.md).
- **Journal detail pages** — APC costs, quartile trends, OA classification,
  deal coverage, institutional output, and similar journals.
- **Deal register** — the institution's current NL open-access deals with
  journal counts, harvested from openaccess.nl and enriched from the JCT
  ESAC dump. See [Deals](../systems/data-model.md).
- **Author and org-unit pages** — per-researcher publication profiles built
  from the institution's Pure corpus, with identity resolution to OpenAlex.
- **Admin panel** — settings, deal curation, author identity review,
  feedback triage, and harvest-run inspection. See [Admin panel](../features/admin.md).
- **Feedback loop** — visitors report data problems; the admin triages them.
  See [Feedback](../features/feedback.md).

## Who uses it

Any Dutch (or international) research institute can run its own instance.
One deployment serves several universities at `/{code}` paths (`/ut`,
`/rug`) over a shared data core; a landing page at `/` chooses an
institution. Every UI label follows the configured institution. See
[Multi-institution core](../features/multi-institution.md).

## How it is built

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 (async), managed with `uv` |
| Database | PostgreSQL 17 + pgvector |
| Frontend | Next.js 15 (App Router), React 19, TypeScript |
| External data | OpenAlex, OpenAIRE, Crossref, Pure OAI-PMH, DOAJ, OpenAPC, Scimago, openaccess.nl, JCT/ESAC |
| Deployment | Docker Compose with a one-shot `bootstrap` harvest service |

The distinctive part of the system is the harvest pipeline: a `docker compose
up` on a fresh database runs a two-layer dependency DAG that sweeps the
journal universe, builds the deal register, and harvests each institution's
works before the backend starts serving. See [Architecture](architecture.md)
and [Data pipeline](../systems/data-pipeline/index.md).

## Where to go next

| If you want to… | Read |
|---|---|
| Understand the system design | [Architecture](architecture.md) |
| Run or develop the project | [Getting started](getting-started.md) |
| Learn the vocabulary | [Glossary](glossary.md) |
| Explore the harvest DAG | [Data pipeline](../systems/data-pipeline/index.md) |
| See how the API is organized | [Backend](../apps/backend/index.md) |
| Check project history | [Lore](../lore.md) |
