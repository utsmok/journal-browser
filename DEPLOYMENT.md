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

Copy `.env.example` to `.env` and set the institution levers. The browser is
per-institution by design: the register, the works data, and every UI label
follow these values.

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
| `JB_DATA_WINDOW_START` / `JB_DATA_WINDOW_END` | Inclusive publication-year window for every harvest. `END=0` = open (to now). A smaller window makes a deployment lighter (Groningen runs 2025/2025) | `2020` / `0` |

### Operations

| Variable | What it is | Default |
|---|---|---|
| `JB_DATABASE_URL` | Postgres DSN | local default |
| `JB_ADMIN_PASSWORD` | Admin panel password (`/admin`); empty disables the panel | empty |
| `JB_BOOTSTRAP` | `auto` (only on an empty DB), `always`, or `off` | `auto` |
| `JB_LANDING_DIR` | Raw landing zone for downloaded files. Compose pins the bind mount to `./backend/landing`; the variable applies to non-compose runs | `backend/landing` |
| `JB_UT_METADATA_DSN` | Twente-only: read-only ut-metadata Postgres for canonical works. Leave empty elsewhere; the works endpoints degrade to stats-only | empty |

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
shows the harvest run history with stats, deals flagged for curation, and the
effective non-secret settings (secrets appear as booleans only). Login
exchanges the password for a 12-hour signed token; the panel is read-only by
design — configuration changes belong in `.env` plus a restart, so the panel
cannot drift from the deployment.

## Deploying a second institution

`compose.groningen.yml` is the tested reference (University of Groningen,
ports 5543/8002/3002):

```bash
docker compose -p jb-groningen -f docker-compose.yml -f compose.groningen.yml up -d --build
```

The override sets Groningen's identity and display variables, their Pure
OAI-PMH endpoint (`https://pure.rug.nl/ws/oai`), their OpenAIRE org id, a
2025-only data window, an isolated landing directory, and its own ports. Copy
the pattern for another institute: identity block, sources block, ports,
landing dir. Nothing else in the image is institution-specific.

## Maintenance

- **Re-harvest on demand:** every job is a standalone script under
  `backend/jobs/`; run any of them through the bootstrap image (see
  First boot variants). `JB_BOOTSTRAP=always` reruns the full pipeline.
- **After hand-fixing a deal** (alias, participation, merge): rerun
  `jobs/reconcile.py`. It re-derives, re-merges, refreshes coverage flags,
  and rewrites the curation report.
- **Updating Scimago quartiles:** drop the new year's CSV into
  `backend/data/` and rerun `jobs/ingest_scimagojr.py`.
- **Upgrading the stack:** `git pull && docker compose up -d --build`. Check
  this file's changelog-worthy notes before major version bumps; new settings
  always default to the Twente values, so existing deployments keep working.
