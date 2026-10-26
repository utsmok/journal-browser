# Deploying the Journal Browser

Everything beyond the README quick start: configuration reference, what the
first boot does, how the deal register is built, admin panel, second-institute
deployment, and maintenance.

Written for the operator of an instance. All commands run from the repository
root unless noted.

## Prerequisites

- Docker with Compose v2.24+ (the test and per-institute overrides use the
  `!override` merging feature).
- About 10 GB of disk for the database plus the raw landing zone.
- A free [OpenAlex API key](https://openalex.org) for the journals sweep.

## Configuration

Copy `.env.example` to `.env` and set the institution levers. These values
configure the **default institution** — the one the first boot harvests and
serves at its `/{code}` path. Additional universities are configured as
`institutions` rows in the database (see "Adding a second institution");
their display values, sources, and data windows come from their row, not
from `.env`. The admin panel's settings overlay `backend/settings.yaml`
overrides any of these keys and reloads live (see "Admin panel").

### Institution identity and display

| Variable | What it is | Default | How to find / set it |
|---|---|---|---|
| `JB_INSTITUTION_NAME` | English name as openaccess.nl deal pages write it; drives deal matching and all long UI labels | `University of Twente` | openaccess.nl deal pages |
| `JB_INSTITUTION_SHORT` | Short name for compact labels ("Twente works", "Groningen works") | `Twente` | your choice |
| `JB_INSTITUTION_ROR` | ROR id; resolves the OpenAlex institution filter | `https://ror.org/006hf6230` | <https://ror.org> search |
| `JB_LIBRARY_URL` | Library homepage shown in footer and About | UT library | your library site |
| `JB_OA_GUIDE_URL` | Open access publishing guide link | UT service-portal page | your library's OA page |
| `JB_SUPPORT_EMAIL` | Support email shown in footer and About | `open-access@utwente.nl` | your OA support address |
| `JB_ADMIN_CONTACT` | Personal admin contact in footer/About; empty hides the row | `s.mok@utwente.nl` | your choice |
| `JB_RESEARCH_PORTAL_URL` | Research portal (Pure) link in data-source attributions | `https://research.utwente.nl` | your portal |

The backend serves these from `GET /api/v1/meta/freshness`, and the frontend
server seeds its first render from the same variables, so a change needs
`docker compose up -d` (recreating the containers), not an image rebuild.

One display value is baked at build time instead: `NEXT_PUBLIC_SITE_URL`
(default `https://journalbrowser.samuelmok.cc`) is the public hostname used
in citation links on journal pages. Set it in `.env` before the first
`docker compose up -d --build` of a new instance.

### Harvesting sources

| Variable | What it is | Default |
|---|---|---|
| `JB_PURE_OAI_BASE_URL` | Your repository's anonymous OAI-PMH endpoint (works data) | `https://ris.utwente.nl/ws/oai` |
| `JB_OPENAIRE_ORG_ID` | OpenAIRE organization id (`openorgs____::...`). **Required**; unset = the OpenAIRE harvest is off. Not derivable from the ROR — look it up at `api.openaire.eu/graph/v1/organizations?legalName=<name>` | unset |
| `OPENALEX_API_KEY` | Free OpenAlex key; needed for cursor-paged harvests only | unset |
| `JB_CONTACT_EMAIL` | Polite-pool identification sent to OpenAlex | `s.f.abma@utwente.nl` |
| `JB_DATA_WINDOW_START` / `JB_DATA_WINDOW_END` | Inclusive publication-year window for the default institution's harvests. `END=0` = open (to now). A smaller window makes a deployment lighter (Groningen runs 2025/2025; additional institutions carry their window on their row) | `2020` / `0` |

### Operations

| Variable | What it is | Default |
|---|---|---|
| `JB_DATABASE_URL` | Postgres DSN | local default |
| `JB_ADMIN_PASSWORD` | Admin panel password (`/admin`); empty disables the panel | empty |
| `JB_BOOTSTRAP` | `auto` (only on an empty DB), `always`, or `off` | `auto` |
| `JB_LANDING_DIR` | Raw landing zone for downloaded files. Compose pins the bind mount to `./backend/landing`; the variable applies to non-compose runs | `backend/landing` |
| `JB_UT_METADATA_DSN` | Twente-only: read-only ut-metadata Postgres for canonical works + the author roster (`authors` bootstrap step; skips cleanly when empty). Leave empty elsewhere; the works endpoints degrade to stats-only and `/authors` reports `enabled: false` | empty |

## First boot

```bash
cp .env.example .env   # then edit
docker compose up -d --build
docker compose logs -f bootstrap
```

The one-shot `bootstrap` service runs `backend/jobs/bootstrap.py`, which
executes the harvest jobs as a dependency DAG: independent steps (OpenAlex
journals, the two deal harvests, OpenAPC, your repository) run concurrently,
and everything else starts as soon as its inputs are in. A failed step stops
new steps from launching and is named in the summary; the backend service
stays down until the pipeline succeeds, so a half-filled database is never
served.

Expect the first boot to take 1.5–2 hours, dominated by the OpenAlex journals
sweep (~60 min for the ~177k journal universe) and journal embeddings (~45 min
on CPU). Subsequent restarts are cheap: `auto` mode skips the pipeline when
journals already exist.

Useful variants (run inside the backend image, e.g.
`docker compose run --rm bootstrap uv run python jobs/bootstrap.py --always`):

- `--always` re-runs the whole pipeline (every job is idempotent).
- `--from <step>` re-runs one step and everything after it, serially, in the
  listed order — the repair path.
- `--institution <code>` re-runs only that institution's layer (repository
  harvest, enrichment, OpenAIRE, stats, participation, flags, authors).
  Global steps are skipped — the shared layer is already in place.

## What the harvests build

| Job | Source | Produces |
|---|---|---|
| `harvest_journals` | OpenAlex | The journal universe (~177k rows), ISSNs, topics, OA status |
| `scrape_openaccess_nl` | openaccess.nl | Deal pages: narrative, conditions, participation text |
| `ingest_jct` | cOAlition S JCT public dump | ESAC agreements + journal lists |
| `reconcile` | the two above | The deal register; participation per hosted institution (non-participation = no `deal_institutions` row; shared deals are never deleted) |
| `backfill_issn_l` | issn_map | Links deal journal ISSNs to the canonical ISSN-L |
| `ingest_openapc` | OpenAPC dataset | APC evidence and per-journal aggregates |
| `ingest_scimagojr` | seeded from `backend/data/` | Quartiles (scimagojr.com is Cloudflare-hard; drop fresh CSVs in `backend/data/` to update) |
| `harvest_pure` | your repository OAI-PMH | The works corpus |
| `enrich_works` | OpenAlex + Crossref | DOIs, types, citation counts per work |
| `harvest_openaire` | OpenAIRE Graph | Institution works matched by DOI |
| `harvest_stats` | all of the above | Per-journal, per-year statistics |
| `backfill_flags` | register + stats | Curation flags, browse visibility |
| `ingest_authors` | external canonical-works DB (`JB_UT_METADATA_DSN` / `external_works_dsn`) | Per-institution author roster: identity, faculty/research group/org derivation, work edges (skips cleanly without a DSN) |
| `embed_journals` | stats-built text | Journal embeddings for similar-journals |

### The deal register

Deals come from openaccess.nl (the canonical NL narrative) reconciled with
the JCT/ESAC dump. Rules:

- An ESAC sheet links to your institution through the consortium affiliation
  or an enumerated participant list; name variants ("University of Groningen"
  vs "Groningen University") are matched.
- Deals that exist only on openaccess.nl (ACM, ACS, AUP, IOS Press, ...) are
  derived: participation is parsed from the page's conditions text, coverage
  is the publisher's journal corpus. A page whose list omits your institution
  leaves the deal unlinked, and the purge drops it — that is correct
  behavior, not a bug (live case: Twente is not in the LWW 2024-2026
  agreement; Groningen is).
- `reconcile` merges duplicate sources for one agreement (ESAC code aliases
  map to the openaccess.nl publisher name) and refreshes the search-side
  deal-coverage flags, so rerunning it after any register fix is safe and
  self-contained.
- `ManualOverride` rows keep hand fixes winning over re-harvests. The
  curation report (`landing/reports/curation_report.html`) lists everything
  that needs a human.

## Admin panel

Set `JB_ADMIN_PASSWORD` and restart the backend. `http://<host>/admin` then
shows the harvest run history with stats and deals flagged for curation,
edits the settings (`backend/settings.yaml`, reloaded live — no restart;
YAML values override `.env`), and edits per-institution configuration rows
(institution fields, sources, data windows; secrets stay masked). Runs carry
an institution column — shared/global steps are labeled "shared", and a
dropdown filters the list to one institution. Login exchanges the password
for a 12-hour signed token; changing the password in the panel invalidates
old tokens immediately.

## Adding a second institution

One deployment serves any number of universities at `/{code}/...` paths
(for example `/ut` and `/rug`). The journal universe, deal register,
OpenAPC, Scimago, and embeddings are shared; each institution only adds
its own works corpus, stats, and participation. Onboarding is one SQL
statement plus one harvest run — no second stack, no extra ports:

```sql
-- The institutions table already lists every openaccess.nl participant
-- (inactive, no code); claim the row instead of inserting a new one.
UPDATE institutions SET
  code = 'rug', short_name = 'RUG', active = true,
  ror = 'https://ror.org/012p63287',
  pure_oai_base_url = 'https://pure.rug.nl/ws/oai',
  openaire_org_id = 'openorgs____::81371ea94b1a09d3243e73d6ec3527ec',
  data_window_start = 2025, data_window_end = 2025,
  library_url = 'https://www.rug.nl/library',
  support_email = 'openaccess@rug.nl'
WHERE name = 'Rijksuniversiteit Groningen';
```

```bash
# Runs only the per-institution layers (pure, enrich, openaire, stats,
# participation, flags); the global layer is already in place.
docker compose run --rm bootstrap sh -c "uv run --no-dev python jobs/bootstrap.py --institution rug"
```

The landing page (`/`) lists every active institution and redirects to it
when only one exists. `JB_*` env vars still configure the default
institution; every other institution reads its config from its row.

## Maintenance

- **Re-harvest on demand:** every job is a standalone script under
  `backend/jobs/`; run any of them through the bootstrap image (see
  First boot variants). `JB_BOOTSTRAP=always` reruns the full pipeline.
- **After hand-fixing a deal** (alias, participation, merge): rerun
  `jobs/reconcile.py`. It re-derives, re-merges, refreshes coverage flags,
  and rewrites the curation report.
- **Updating Scimago quartiles:** drop the new year's CSV into
  `backend/data/` and rerun `jobs/ingest_scimagojr.py`.
- **Importing the ut-metadata corpus (Twente):** with `JB_UT_METADATA_DSN`
  set, `jobs/import_utmetadata_works.py` copies every canonical work that
  maps to a Pure uuid into `works` — the full year range without a
  re-harvest — refreshes the stats and journal flags, and widens the
  institution's data window to the oldest stored work. Idempotent; canonical
  works without a Pure uuid stay out (they still surface on journal pages
  through the live merge). `jobs/import_utmetadata_raw.py` then copies the
  verbatim OpenAlex / OpenAIRE / Pure / Crossref work records behind that
  corpus into `source_records`, reconfirms OpenAIRE DOI identities, and
  rebuilds the OpenAlex per-journal/year OA stats window-bounded — so
  year charts and FWCI/citation metrics cover the whole data window, not
  just the years the live harvests ran.
- **Upgrading the stack:** `git pull && docker compose up -d --build`. The
  bootstrap service applies pending migrations before harvesting. Migration
  0020 (semantic-search index) builds an HNSW graph and needs a few minutes
  plus about 100 MB of Postgres shared memory (compose sets
  `db.shm_size: 512mb`; raise it for external databases). Check this file's
  changelog-worthy notes before major version bumps; new settings always
  default to the Twente values, so existing deployments keep working.

## Backbone export

Everything institution-neutral lives in global tables with no institution
columns, so a filled database doubles as a bootstrap backbone for a fresh
instance (another university's own deployment starts hours ahead by
restoring them before its first boot):

| Table | Contents |
|---|---|
| `journals` | OpenAlex journal universe (ISSN-L keyed) |
| `issn_l_map` | ISSN to ISSN-L resolution |
| `publishers`, `deals`, `deal_journals` (shared rows: `institution_id IS NULL`) | NL deal register and journal lists |
| `apc_evidence`, `openapc` | APC evidence and OpenAPC prices |
| `scimagojr_metrics` | Scimago quartiles |
| `jct` | Journal Checker Tool data |
| `journals.embedding` (column) | Semantic-search vectors (institution-neutral; HNSW-indexed) |
| `works_metadata_cache` | OpenAlex per-work enrichment cache |

Export with `pg_dump -Fc -t journals -t issn_l_map ...` and restore into the
fresh database before `docker compose up`; `auto` bootstrap then only runs
the institution-specific layers. Institution-scoped tables (`works`,
`institution_works_stats`, `journal_flags`, `harvest_runs`,
`harvest_state`, `deal_institutions`, plus per-institution `deal_journals`
rows) stay behind — they are per-deployment data.
