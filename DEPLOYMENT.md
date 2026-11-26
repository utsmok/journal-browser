# Deploying the Open Journal Browser

Everything beyond the README quick start: configuration reference, what the
first boot does, how the deal register is built, admin panel, second-institute
deployment, the daily refresh wave, and maintenance.

Written for the operator of an instance. All commands run from the repository
root unless noted.

## Prerequisites

- Docker with Compose v2.24+ (the test and per-institute overrides use the
  `!override` merging feature).
- Memory: 12–16 GB RAM recommended for a multi-institution instance (`db` 6g with
  `shared_buffers=1GB` and `effective_cache_size=4GB`, `scheduler` 3g,
  `bootstrap` 3g, `backend` 2g, `frontend` 512m).
- Disk, measured on the Twente-scale live instance: about 130 GB for the
  database volume, plus the raw landing zone and one `pg_dump -Fc` archive
  per night (an estimated 6.5 GB each with zstd compression; the default
  retention keeps 7). The bulk of the database was the `journal_flags`
  table materialized for every known institution; pruning it to active
  institutions shrinks the database by roughly 90 GB. A narrower data
  window or a smaller institution needs far less.
- A free [OpenAlex API key](https://openalex.org) for the journals sweep.

## Configuration

Copy `.env.example` to `.env` and set the institution levers. These values
configure the **default institution** — the one the first boot harvests and
serves at its `/{code}` path. Additional universities are configured as
`institutions` rows in the database (see "Adding a second institution");
their display values, sources, and data windows come from their row, not
from `.env`. The admin panel's settings overlay
`backend/state/settings.yaml` overrides any of these keys and reloads
live (see "Admin panel").

### Institution identity and display

| Variable | What it is | Default | How to find / set it |
|---|---|---|---|
| `JB_INSTITUTION_CODE` | URL path segment (`[a-z0-9-]+`) for the default institution | `ut` | short code (e.g. `ut`, `rug`) |
| `JB_INSTITUTION_NAME` | English name as openaccess.nl deal pages write it; drives deal matching and all long UI labels | `University of Twente` | openaccess.nl deal pages |
| `JB_INSTITUTION_SHORT` | Short name for compact labels ("Twente works", "Groningen works") | `Twente` | your choice |
| `JB_INSTITUTION_ROR` | ROR id; resolves the OpenAlex institution filter | `https://ror.org/006hf6230` | <https://ror.org> search |
| `JB_LIBRARY_URL` | Library homepage shown in footer and About | UT library | your library site |
| `JB_OA_GUIDE_URL` | Open access publishing guide link | UT service-portal page | your library's OA page |
| `JB_SUPPORT_EMAIL` | Support email shown in footer and About | `open-access@utwente.nl` | your OA support address |
| `JB_ADMIN_CONTACT` | Personal admin contact in footer/About; empty hides the row | empty | your choice |
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
| `OPENALEX_API_KEY` | Free OpenAlex key. Listing/cursor sweeps (institution stats, the author sweep, `--sweep-all`) refuse to start without it — keyless requests serve only the first cursor page | unset |
| `JB_OPENALEX_RESERVE_USD` | Daily-budget floor in USD: credit-priced list/search OpenAlex stages stop cleanly, with a stats note, once the remaining budget falls below it (see `harvest.common.openalex_budget_ok`; `$0` singleton GET stages run ungated unless upstream pricing drift is detected) | `0.25` |
| `JB_JISC_API_KEY` | Jisc Open Policy Finder API key; without it the JISC sweep skips cleanly | unset |
| `JB_CONTACT_EMAIL` | Polite-pool identification sent to OpenAlex, and the contact in the ROR harvest's User-Agent. Set it in `.env`; an empty value sends anonymous requests | empty (the live deployment sets `s.f.abma@utwente.nl`) |
| `JB_DATA_WINDOW_START` / `JB_DATA_WINDOW_END` | Inclusive publication-year window for the default institution's harvests. `END=0` = open (to now). A smaller window makes a deployment lighter (Groningen runs 2025/2025; additional institutions carry their window on their row) | `2020` / `0` |

### Operations

| Variable | What it is | Default |
|---|---|---|
| `JB_DATABASE_URL` | Postgres DSN | local default |
| `JB_DB_POOL_SIZE` / `JB_DB_MAX_OVERFLOW` | API engine pool: connections kept open, and extra connections allowed under load (30 at most with the defaults). Postgres allows 97 ordinary connections by default (`max_connections` 100) and the scheduler's job engines draw from the same number, so raise `max_connections` before raising these. A connection running a sort may use `work_mem` (64 MB) | `10` / `20` |
| `JB_DB_POOL_TIMEOUT` | Seconds a request waits for a pool connection before it fails | `30` |
| `JB_ADMIN_PASSWORD` | Admin panel password (`/admin`); empty disables the panel | empty |
| `JB_BOOTSTRAP` | `auto` (skips only a completed pipeline; refuses a partial one), `always`, or `off` | `auto` |
| `JB_LANDING_DIR` | Raw landing zone for downloaded files. Compose pins the bind mount to `./backend/landing`; the variable applies to non-compose runs | `landing` |
| `JB_UT_METADATA_DSN` | Twente-only: read-only ut-metadata Postgres for canonical works + the author roster (`authors` bootstrap step; skips cleanly when empty). Leave empty elsewhere; the works endpoints degrade to stats-only and `/authors` reports `enabled: false`. Currently off on the live demo — the works-merge features run on stats data only | empty |
| `JB_ENABLE_USAGE_TRACKING` | Anonymous usage events (page paths, searches, coarse audience info; no cookies). `false` accepts and drops event batches instead of storing | `true` |
| `JB_USAGE_RETENTION_DAYS` | Days usage events are kept before being nulled; `0` disables expiry | `90` |
| `JB_RATE_LIMIT_PER_MINUTE` | Requests per minute each client IP may make to `/api`; `0` turns the limit off. See [Public API](#public-api) | `600` |
| `JB_RATE_LIMIT_HEAVY_PER_MINUTE` | Separate per-IP limit for CSV exports and the semantic search, recommendation and similar-journal routes | `60` |
| `JB_RATE_LIMIT_FEEDBACK_PER_MINUTE` | Separate per-IP limit for feedback submissions | `10` |
| `JB_STATEMENT_TIMEOUT_MS` | Longest API statement, in ms, before it fails instead of holding a pool connection | `60000` |
| `JB_CACHE_MAX_MB` | RAM the three in-process caches (search facets, list snapshots, stale detail bundles) may hold together, estimated from the cached objects. Above it the least recently used entry goes first, whichever cache holds it. One orgunit snapshot holds about 100 MB, so leave room for it inside the backend's 2 GB container limit | `256` |
| `JB_WORK_FUNDERS_TTL_DAYS` | Days before `harvest_work_funders` re-fetches a work's funder records | `30` |
| `JB_LOG_FORMAT` | `text` (human-readable with `[request-id]`) or `json` (one JSON object per line) | `text` |
| `JB_SETTINGS_YAML` | Path to admin-editable runtime settings overlay (mounted at `./backend/state/settings.yaml` in compose) | `settings.yaml` |
| `TZ` | Container timezone for scheduler cron logs | `UTC` |
| Country lookups | `jobs/enrich_usage_geo.py` resolves visitor IPs locally against DB-IP's free Country Lite database (downloaded monthly into `landing/dbip/`). Country data by DB-IP.com, CC BY 4.0 (https://db-ip.com) | — |
| `JB_IGNORED_ISSNS` | JSON list of ISSNs the browser treats as nonexistent on every journal surface | empty |
| `JB_SOURCE_WAVE_CRON` | Cron schedule (UTC) for the weekly source wave, run by the `scheduler` service | `0 22 * * 0` (Sunday 22:00) |
| `JB_REFRESH_WAVE_CRON` | Cron schedule (UTC) for the nightly harvest wave, run by the `scheduler` service | `30 1 * * *` |
| `JB_BACKUP_CRON` | Cron schedule (UTC) for the nightly database backup | `0 4 * * *` |
| `JB_BACKUP_KEEP` | Nightly dump archives kept in `./backups` | `7` |
| `JB_ALERT_WEBHOOK_URL` | Incoming webhook (Slack or Mattermost) that receives one JSON message when a wave or the backup fails, or when a killed wave is found. See [Nightly scheduler](#nightly-scheduler) | unset |
| `JB_ALERT_HOST` | Name of this deployment in those alerts | container hostname |
| `JB_HEARTBEAT_URL` | Fallback URL that each wave and the backup ping once after ending well (healthchecks.io style) | unset |
| `JB_HEARTBEAT_REFRESH_URL` / `_SOURCE_URL` / `_BACKUP_URL` | Optional per-job heartbeat URLs for `refresh_wave.sh`, `source_wave.sh`, and `backup.sh` (each falls back to `JB_HEARTBEAT_URL`) | unset |

## First boot

`backend` waits for the one-shot `bootstrap` service, so a plain
`docker compose up -d --build` blocks for the whole first harvest (1.5-2
hours) before returning. Start the database and the bootstrap explicitly,
follow the bootstrap log, then bring up the rest:

```bash
cp .env.example .env   # then edit
docker compose build backend        # builds the one image all three backend services share
docker compose up -d db bootstrap
docker compose logs -f bootstrap    # Ctrl-C any time; the pipeline keeps running
# once the log shows the bootstrap summary:
docker compose up -d
```

Existing deployments that predate the `backend/state/` settings directory
move their overlay once, before the redeploy that introduces it (the file
is gitignored; fresh clones need nothing because the entrypoint seeds the
example):

```bash
mkdir backend/state && mv backend/settings.yaml backend/state/
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
on CPU). Subsequent restarts are cheap: `auto` mode skips the pipeline only
when a plan run completed and left its marker in `harvest_state` (source
`local`, entity type `bootstrap_plan`; written by bootstrap itself on exit
0 and seeded for pre-marker deployments by the baseline migration). When journals
exist but that marker is missing (a bootstrap died partway), `auto` exits
nonzero and names the repair path instead of quietly serving a
half-filled database.

Useful variants (run inside the backend image, e.g.
`docker compose run --rm bootstrap uv run python jobs/bootstrap.py --always`):

- `--always` re-runs the whole pipeline (every job is idempotent).
- `--from <step>` re-runs one step and everything after it, serially, in the
  listed order — the repair path.
- `--institution <code>` re-runs only that institution's layer (repository
  harvest, CERIF enrichment, enrichment, OpenAIRE, stats, participation,
  flags, author-edge backfill, authors).
  Global steps are skipped — the shared layer is already in place.

## What the harvests build

The table follows the bootstrap order (`jobs/bootstrap.py` GLOBAL_STEPS,
then INST_STEPS, then the shared funder chain and embeddings); the daily
wave (see "Daily refresh wave" below) repeats a subset of these stages.

| Job | Source | Produces |
|---|---|---|
| `harvest_journals` | OpenAlex | The journal universe (~177k rows), ISSNs, topics, OA status. Default route is credit-free (deal seed + singleton delta for missing journals; singleton GETs bill $0); `--refresh` re-fetches every stored journal via $0 singleton GETs to pick up upstream corrections (counts fields), `--sweep-all` costs credits ($0.0001 per page) and is a rare manual operation that requires an API key |
| `harvest_publishers` | OpenAlex | Publisher lineage: `journals.publisher_canonical` groups sub-brands (e.g. IEEE Communications Society) under their root publisher. Ids absent from a response cache as NULL-lineage rows and are retried after a week. Credit-priced only on a fresh install |
| `scrape_openaccess_nl` | openaccess.nl | Deal pages: narrative, conditions, participation text |
| `ingest_jct` | cOAlition S JCT public dump | ESAC agreements + journal lists |
| `ingest_oaforward` | OA Forward registry of open publishing agreements | Agreements a hosted institution signed itself (no journal lists) |
| `reconcile` | the two above | The deal register; participation per hosted institution (non-participation = no `deal_institutions` row; shared deals are never deleted) |
| `backfill_issn_l` | issn_map | Links deal journal ISSNs to the canonical ISSN-L |
| `ingest_openapc` | OpenAPC dataset | APC evidence and per-journal aggregates |
| `ingest_scimagojr` | tracked seed CSVs, materialized into landing on first use | Quartiles (scimagojr.com is Cloudflare-hard; to update, drop `export_<year>.csv` into `backend/landing/scimagojr/` and rerun the job — `backend/data/` holds the tracked first-boot seeds only) |
| `backfill_flags` | register + stats | Curation flags, browse visibility |
| `harvest_oa_colors` | locally stored OpenAlex works | Observed OA status on journals. Fills NULLs only — it never refreshes a color already set, so rerunning is safe but never corrects old values |
| `harvest_doaj` | DOAJ bulk CSV | DOAJ canon: `doaj_in_doaj`, APC flags per journal |
| `harvest_jisc` + `normalize_jisc` | Jisc Open Policy Finder | Green-OA policies per journal (`jisc_*` columns). Skips cleanly when `JB_JISC_API_KEY` is unset; run `normalize_jisc` after the sweep to stamp the journal columns |
| `harvest_pure` | your repository OAI-PMH | The works corpus |
| `harvest_pure_entities` | your repository OAI-PMH (CERIF sets) | Orgunits, persons, publication author lists (`pure_orgs`, `pure_persons`, `work_pure_authors` inputs) |
| `enrich_works` | OpenAlex + Crossref | DOIs, types, citation counts per work (OpenAlex rung: $0 singleton GETs, runs ungated); the Crossref rung lands the payloads the author ORCID corroboration reads |
| `harvest_openaire` | OpenAIRE Graph | Institution works matched by DOI |
| `derive_openaire_facts` | stored OpenAIRE products | Per-work facts row: diamond flag, usage, FOS, projects |
| `harvest_stats` | all of the above | Per-journal, per-year statistics. Credit-priced works filter ($0.0001 per page); stops cleanly below the budget reserve |
| `build_openalex_works` | stored works-stats payloads | The normalized OpenAlex works store behind the works tab and the standalone author path |
| `backfill_parts` | OpenAlex ($0 single-entity GETs) | Part-of chips for Graph v12 payloads; resumable and idempotent |
| `backfill_pure_authors` | stored CERIF publication records | The `pure-authors` step: full-replaces each work's pure authorship edges (`work_pure_authors`) from the latest stored record; runs after `openalex-works`, before author-id resolution, so it also covers works whose CERIF record predated author extraction |
| `resolve_author_ids` | OpenAlex works listings + $0 singleton GETs | Author identity resolution (the cascade); budget-capped: stops below the reserve, needs an API key for the works listings |
| `ingest_authors` | local stores by default (`author_source=local`; the `JB_UT_METADATA_DSN` canonical-works DB is an opt-in accelerator) | Per-institution author roster: identity, faculty/research group/org derivation, work edges; also fills `crossref_orcid` from the stored Crossref payloads — run `enrich_works` first for maximum coverage |
| `harvest_work_funders` | OpenAlex ($0 single-entity GETs per DOI, staleness-gated: only works whose last fetch is older than 30 days) | `work_funders`: grant lines per work |
| `harvest_openalex_funders` | OpenAlex ($0 singleton GETs) | `openalex_funders` gap-filled from works-linked funder ids |
| `harvest_openaire_funders` | OpenAIRE Graph | Curated funder canon pull |
| `derive_work_partners` | stored OpenAlex and OpenAIRE work payloads | `work_partners` (one row per work and partner ROR id) and stub `partner_institutions` rows for the Partners page |
| `derive_funder_aliases` | stored `work_funders` and OpenAIRE projects | `funder_aliases`: OpenAIRE funder names resolved to OpenAlex funders, by display name or by shared grant numbers |
| `harvest_ror` | ROR API (free, no key) | `partner_institutions`: name, type, place and coordinates per partner; refreshes records older than 30 days |
| `harvest_people_utwente` | people.utwente.nl directory (its own JSON-RPC search endpoint) | Per-author people profile: portrait, canonical name, email, org list, org edges resolved onto `pure_orgs` (`people_utwente_person_orgs`, gap-fill evidence like `pure_person_orgs`), and the profile's research.utwente.nl portal link as the match oracle. Runs 20 author pipelines in flight (`--concurrency`), so the confirmed roster takes roughly 30-45 minutes; external — keep it out of the daily wave. Outcomes are stamped in batches of 50, so re-runs only see new authors (`--retry-missed` / `--refresh` re-open old ones) |
| `embed_journals` | stats-built text | Journal embeddings for similar-journals |

Recommendation surfaces (journal similar lists, author similar lists and
alternatives, the journal finder) only offer journals with OpenAlex works in
the current or previous year that Scimago, DOAJ, an institutional deal, or an
OpenAlex `listed_in` entry vouches for (`services/search/recommendable.py`).
`harvest_journals` refreshes `journals.listed_in` and `last_active_year`, so
run it with `--refresh` when those inputs look stale. Browse and semantic
search apply the same two filters by default; users can switch each off
(`active=false`, `vouched=false`).

### APC prices

Two sets of columns keep a publisher's list price apart from what authors
paid. Both are recomputed by `harvest.denorm.refresh_apcs`, which runs after
`ingest_openapc`, `harvest_journals` and `harvest_doaj`.

- `journals.list_price_source`, `_currency`, `_amount`, `_year` and `_euro`
  hold the publisher's list price. The OpenAlex `apc_prices` entry wins: EUR
  first, then USD, then an entry with an exchange rate, then the first
  entry. Without one, the DOAJ maximum APC is used. `_year` is the year that
  source was last harvested, because neither source dates its price. `_euro`
  is the amount in euros at the 1 January ECB rate of the year of the
  refresh, or NULL when the currency has no rate.
- `journals.latest_apc_euro` and `latest_apc_period` hold the mean amount
  paid in the newest OpenAPC period with an article paid above €0. OpenAPC
  records an article that an agreement paid for as €0, and some rows carry
  no amount (`NA`). Both kinds count in `article_count` only, and the €0
  ones also in `journal_apc_aggregates.zero_count`; `paid_count` counts the
  rest. `euro_min`, `euro_max` and `euro_mean` cover the paid articles.

Browse, the APC filter and sort, and the finder budget use the list price.
They fall back to the paid mean for a journal without a list price. After
migration 0005, periods that mixed paid and €0 articles keep approximate
figures until `uv run python jobs/ingest_openapc.py` rebuilds the table.

### Manual and repair jobs

Not in bootstrap or the daily wave. All run from `backend/` as
`uv run python jobs/...`:

| Job | When to use it |
|---|---|
| `import_pure_export.py` | Manual ops import (`--file PATH`): stores a Pure backend export verbatim as `work_cerif_full`. The OAI stream truncates author identity; run this before/with the `pure-authors` backfill so author lists are full |
| `jobs/oneoff/import_utmetadata_works.py` | Twente only: copies the ut-metadata canonical works into `works` (full year range without a re-harvest); needs `JB_UT_METADATA_DSN` |
| `jobs/oneoff/import_utmetadata_raw.py` | Twente only: copies the verbatim OpenAlex/OpenAIRE/Pure/Crossref records behind that corpus into `source_records` and rebuilds the OA stats window |
| `jobs/oneoff/verify_utmetadata.py` | Dev-only gate comparing the local works table against ut-metadata (needs a reachable DSN) |
| `jobs/oneoff/bulk_work_identity.py` | Deploy-time curation: bulk-confirm/bulk-miss work identities from a decisions file |
| `jobs/oneoff/ingest_emerald_contract.py <contract.xlsx>` | Repair while JCT serves the wrong UKB sheet upstream: rebuilds the Emerald deal journal list from the signed contract's title list (pass the xlsx path as the argument) |
| `jobs/funder_link_matrix.py` | Prints the funder-to-institution link matrix (report) |
| `jobs/enrich_usage_geo.py` | Backfills `usage_events.country` from the local DB-IP Lite database (downloads the monthly file on first use) |
| `jobs/backfill_parts.py` | Also safe standalone: re-runs until no works lack a part-of check |
| `jobs/harvest_portal_persons.py` | research.utwente.nl portal persons + the ORCID disambiguation file |
| `jobs/harvest_pure_portal.py` | research.utwente.nl organisation tree scrape |
| `prune_source_records.py` | Deletes superseded `source_records` payload versions. Dry run by default, `--apply` deletes. See [source_records retention](#source-records-retention) |
| `strip_source_records.py` | Removes the payload keys that the ingest projection no longer stores from rows written before it existed. Dry run by default, `--apply` rewrites. See [source_records retention](#source-records-retention) |

### The deal register

Deals come from openaccess.nl (the canonical NL narrative) reconciled with
the JCT/ESAC dump. Rules:

- An ESAC sheet links to your institution through the consortium affiliation
  or an enumerated participant list; name variants ("University of Groningen"
  vs "Groningen University") are matched.
- Deals that exist only on openaccess.nl (ACM, ACS, AUP, IOS Press, ...) are
  derived: participation is parsed from the page's conditions text, coverage
  is the publisher's journal corpus. A page whose list omits your institution
  leaves the deal unlinked — that is correct
  behavior, not a bug (live case: Twente is not in the LWW 2024-2026
  agreement; Groningen is).
- An agreement your institution signed itself, outside the national deals,
  comes from the OA Forward registry (`ingest_oaforward`). The job keeps the
  rows whose licensee is a name of an active institution: its name, its short
  name, or a name on its ROR record. The registry has no journal list, so a
  current agreement covers no journals and stays flagged for curation until
  an admin adds its list in the deal editor. Expired agreements land as
  `archive`. `reconcile` never merges these rows into a national deal. A newly
  onboarded institution gets its agreements on the next weekly source wave.
- `reconcile` merges duplicate sources for one agreement (ESAC code aliases
  map to the openaccess.nl publisher name) and refreshes the search-side
  deal-coverage flags, so rerunning it after any register fix is safe and
  self-contained. Publisher-pattern coverage re-derives on every run (the
  insert is idempotent), so journals a publisher adds later join the deal;
  a deal with hand-curated coverage rows (`source` `manual` or `jct`)
  keeps its frozen list, and `ManualOverride` rows still win over any
  re-harvest. Duplicate narrative rows (a scrape that resolved to a
  differently named publisher row than the canonical agreement, live case
  2026-11-20) fold back into the canonical row: the keeper keeps its period,
  esac identity, and JCT journal list, and adopts the fork's page URL when
  it differed.
- **openaccess.nl is the primary source.** It owns which deals exist for
  your institutions and each deal's publisher, period, status, conditions,
  caps and links. JCT is secondary: it adds what only it has, the ESAC id,
  the journal list and the participants. The JCT ingest never writes its
  placeholder publisher, its status or its End Date onto a deal row that
  has an openaccess.nl page. `restore_openaccess_nl_facts` (the first
  step of `reconcile`) puts those facts back on rows an older ingest
  overwrote: the deal moves to the openaccess.nl publisher row of its ESAC
  code family, and a plain `YYYY-YYYY` duration sets the start and end
  year. A duration with an owner annotation and any field with a
  `ManualOverride` row stay as they are.
- **A JCT journal list is stored only when it is the deal's own.** The JCT
  index can link an agreement to the sheet of another publisher (live
  2026-11: `eme2025ukb`, the Emerald deal, pointed at the Elsevier UKB
  sheet, so 2,572 Elsevier titles counted as Emerald coverage). Before it
  stores a sheet, the ingest resolves the sheet's ISSNs against the
  journal universe and takes the publisher of the majority (at least 50
  journals, more than half of the resolved ones). That publisher must be
  the deal's own family by name (company words such as "BV" or
  "Publishing" are ignored), or the publisher of another stored sheet of
  the same family. When another family's sheets own that publisher, the
  sheet is withheld:
  - no journal rows are stored, and rows an earlier JCT ingest stored
    from it are removed; admin exclusions (`excluded`) and lists from
    other sources (`manual`, `publisher-pattern`) stay;
  - `jct_data_url` stays empty and the sheet's provenance entry carries
    the reason under `sheet_rejected`;
  - the deal is flagged `needs_curation` with a reason that starts with
    `JCT journal list rejected`;
  - the participants are stored anyway: the ESAC id and the consortium
    are the agreement's own, and the openaccess.nl page links it.

  `check_journal_list_publishers` runs in every `reconcile` over the whole
  register and flags, never drops, a deal whose journal list is mostly
  another publisher's (reason starts with `Journal list is mostly another
  publisher's`). A flag with a `sheet_rejected` marker behind it stays
  until the marker is gone, even when the deal carries a correct list from
  another source. Dismissing one of these two reasons in the admin panel
  holds until the cause is gone; the openaccess.nl scrape leaves such a
  dismissal alone.
- `ManualOverride` rows keep hand fixes winning over re-harvests. The
  curation report (`landing/reports/curation_report.html`) lists everything
  that needs a human.

## Admin panel

Set `JB_ADMIN_PASSWORD` and restart the backend. `http://<host>/admin` then
shows the harvest run history with stats and deals flagged for curation,
edits the settings (`backend/state/settings.yaml`, reloaded live — no restart;
YAML values override `.env`), and edits per-institution configuration rows
(institution fields, sources, data windows; secrets stay masked). Runs carry
an institution column — shared/global steps are labeled "shared", and a
dropdown filters the list to one institution. Login exchanges the password
for a 12-hour signed token; changing the password in the panel invalidates
old tokens immediately.

## Public API

Anyone can read the data routes at `/api/v1/institutions` and
`/api/v1/{code}/...` without a key. The reference lives at
`/api/v1/api-docs` (Swagger UI), and its schema at `/api/v1/openapi.json`.
On the live site that is
https://journalbrowser.samuelmok.cc/api/v1/api-docs. The site does not link
to it. The public schema leaves out the admin, feedback, usage, health and
in-app docs routes. The repo-root `openapi.json` is the full schema that the
frontend types come from.

`backend/src/journal_browser/ratelimit.py` limits each client IP per
60-second window, using the three `JB_RATE_LIMIT_*` settings above. An
over-limit request gets `429` with `Retry-After`. Request bodies over 2 MB get
`413`. The client IP is `CF-Connecting-IP` when present, else the first
`X-Forwarded-For` hop, because the live site runs behind Cloudflare. Requests
without either header from a private address are internal (Next.js server
fetches, healthchecks) and skip the limits. The counters live in the single
uvicorn process, so a backend restart resets them.

Every admin route except `POST /api/v1/admin/login` requires the bearer
token. The admin router enforces the token for all of its sub-routers, so a
new admin endpoint is protected even without its own `AdminDep`. Failed
logins lock out a client IP after 5 attempts in 15 minutes, and all clients
after 50.

## Adding a second institution

One deployment serves any number of universities at `/{code}/...` paths
(for example `/ut` and `/rug`). The journal universe, deal register,
OpenAPC, Scimago, and embeddings are shared; each institution only adds
its own works corpus, stats, and participation. Onboarding is one SQL
statement plus one harvest run — no second stack, no extra ports:

```sql
-- Precondition: the first boot has completed. The `institutions` table
-- lists every openaccess.nl participant (inactive, no code) only after
-- the deal ingests have run, so the row to claim does not exist on a
-- fresh database.
-- Match on the ROR id, not the name: display names differ between
-- openaccess.nl and OpenAlex ("Rijksuniversiteit Groningen" vs
-- "University of Groningen"), and the ROR is the stable identifier.
UPDATE institutions SET
  code = 'rug', short_name = 'RUG', active = true,
  pure_oai_base_url = 'https://pure.rug.nl/ws/oai',
  openaire_org_id = 'openorgs____::81371ea94b1a09d3243e73d6ec3527ec',
  data_window_start = 2025, data_window_end = 2025,
  library_url = 'https://www.rug.nl/library',
  support_email = 'openaccess@rug.nl'
WHERE ror = 'https://ror.org/012p63287';

-- Fallback when the row is absent (institution not on openaccess.nl, or
-- the deal ingests have not run yet): insert it.
INSERT INTO institutions
  (name, ror, code, short_name, active, pure_oai_base_url, openaire_org_id,
   data_window_start, data_window_end, library_url, support_email)
SELECT 'University of Groningen', 'https://ror.org/012p63287', 'rug', 'RUG',
       true, 'https://pure.rug.nl/ws/oai',
       'openorgs____::81371ea94b1a09d3243e73d6ec3527ec',
       2025, 2025, 'https://www.rug.nl/library', 'openaccess@rug.nl'
WHERE NOT EXISTS (
  SELECT 1 FROM institutions WHERE ror = 'https://ror.org/012p63287'
);
```

```bash
# Runs only the per-institution layers (pure, enrich, openaire, stats,
# participation, flags); the global layer is already in place.
docker compose run --rm bootstrap sh -c "uv run --no-dev python jobs/bootstrap.py --institution rug"
```

The landing page (`/`) lists every active institution and redirects to it
when only one exists. `JB_*` env vars still configure the default
institution; every other institution reads its config from its row.

Institution-row config (`openaire_org_id`, `data_window_start`, ...) is
seeded from the env only when the baseline migration inserts the row; an existing
row never picks up later env changes. If a step skips with
"has no openaire_org_id" (the OpenAIRE job finishes in seconds), set the
column on the row — the env var will not propagate on its own:

```sql
UPDATE institutions SET openaire_org_id = 'openorgs____::...'
WHERE code = 'ut' AND openaire_org_id IS NULL;
```

## Daily refresh wave

Harvested data goes stale, and rerunning the pipeline one job at a time is
easy to get wrong. `backend/scripts/refresh_wave.sh` runs the repeating set
of harvest and derivation jobs as one sequence, in the order that matters.
Every job in it is idempotent, so rerunning the whole wave or any stage is
safe. The `scheduler` service runs it nightly (see "Nightly scheduler"
below); run it by hand right after the daily OpenAlex credit reset
(00:00 UTC):

```bash
cd backend
bash scripts/refresh_wave.sh
```

The script prints the remaining daily credit budget before the first stage,
because the credit-priced stages must run while that budget is fresh. OpenAlex
bills per request against the free key's $1/day budget, resetting at 00:00 UTC.
Measured 2026-11-20 against the live key: singleton GETs (`/works/{id}`) bill
$0, a list or filter page bills $0.0001, a search bills $0.001. Only list and
search stages draw the budget. Each credit-priced OpenAlex stage checks
`openalex_budget_ok()` before each chunk and stops cleanly, with a stats note,
once the remaining budget falls below `JB_OPENALEX_RESERVE_USD` (default
0.25). Singleton-only stages such as `enrich_works` run ungated: every
request there bills $0. On
2026-11-07 a manually ordered wave spent about seven hours of the fresh
budget on the then credit-priced oa colors step. The funder harvest after it
crashed five seconds in, and the wave's exit gate stopped the remaining
stages. The wave encodes both lessons. Credit-priced stages run at the top,
while the budget is fresh. A failing stage no longer stops the wave: the
stages that need its output are skipped, every other stage still runs, and
the wave exits with code 1 (details follow the stage list).

The stages, in order:

1. `harvest_stats`. It touches credit-priced OpenAlex works filters
   ($0.0001 per page), runs at the top while the budget is fresh, and
   checks `openalex_budget_ok()` before each page: below the
   `JB_OPENALEX_RESERVE_USD` reserve (default 0.25) it stops cleanly and
   notes the stop in its stats output.
2. `build_openalex_works` and `backfill_parts`. The store rebuild derives
   from locally stored data, and `backfill_parts` follows it in the same
   slot: $0 single-entity GETs that fill the part-of chips for OpenAlex
   Graph v12 payloads, resumable and idempotent.
3. `backfill_pure_authors`, then author resolution:
   `resolve_author_ids` + `ingest_authors`. The resolver reads
   `openalex_work_authors` and `work_pure_authors`, which the store
   rebuild and the pure-authors backfill rewrite — running resolution
   after them follows the bootstrap DAG instead of lagging one wave.
   The resolver reads its stores in DOI slices and holds about 0.7 GB on
   the University of Twente's 156k works, inside the scheduler's 2 GB
   limit. Loading the same stores whole took 2.4 GB, and the scheduler
   killed the job before it resolved anyone.
   `resolve_author_ids` also gates on the budget reserve like
   `harvest_stats`. `ingest_authors` is a local projection right after
   identity resolution: it publishes confirmed author identities to the
   served roster and makes no API calls. `harvest_oa_colors` closes this
   block: a local read of `works.oa_status`, which the store rebuild
   re-synced in stage 2.
4. The funder backfills. `harvest_work_funders` fetches works by DOI as
   $0 single-entity GETs and commits per chunk, so an interrupted run
   resumes as a rerun. It only re-fetches a work whose last funders fetch
   is older than 30 days (`--ttl-days` / `JB_WORK_FUNDERS_TTL_DAYS`):
   `work_funders.harvested_at` re-stamps on every fetch, so fresh works
   skip the nightly sweep. Works OpenAlex reports without awards carry no
   rows and stay in the sweep. `harvest_openalex_funders` fetches full
   funder payloads only for ids the table lacks. `harvest_openaire_funders`
   pulls the curated funder canon from the OpenAIRE graph.
   OpenAlex funder ids are stored bare (`F4320321800`, never with the
   `https://openalex.org/` prefix). `refresh_funder_links` writes bare
   ids, and migration 0005 renamed the rows that kept the prefix. It
   links each Jisc funder record to the OpenAlex funders that share its
   ROR or its Funder Registry id. Jisc keeps one record per funding
   programme for some funders, all with the same ROR (the European
   Research Council has FP7, Horizon 2020 and Horizon Europe records), so
   a record for one programme gets only the OpenAlex funder of that
   programme, and the record for the funder as a whole keeps them all.
   When OpenAlex has no funder for a programme (it has none for Horizon
   Europe), the programme record keeps only the links of its own Funder
   Registry id.
5. The collaboration partners. `derive_work_partners` rebuilds
   `work_partners` from the stored OpenAlex and OpenAIRE work payloads
   (OpenAlex first, OpenAIRE for works OpenAlex links to no partner).
   `derive_funder_aliases` resolves OpenAIRE funder names to OpenAlex
   funders, so the Partners page shows each funder once. Both make no API
   calls. `harvest_ror` then fetches the ROR records of new partners and
   refreshes records older than 30 days (`--ttl-days`), paced under ROR's
   limit of 2000 requests per 5 minutes. For a first fill, load the
   monthly ROR data dump instead of asking the API for every partner:
   download the zip from https://zenodo.org/communities/ror-data into
   `backend/state/ror/` and run `jobs/harvest_ror.py --dump
   /app/state/ror/<file>.zip`. The API pass then asks only about the
   partners the dump lacks; later nightly runs fetch the new and stale ones.
   `derive_work_partners` advances a partner's `updated_at` only when the
   stub gives the row a value it lacked, so the 30-day clock counts from
   the last real change and not from last night's derive.
6. `harvest_publishers`. It resolves journal host organizations in
   credit-priced 50-id pipe-filter batches ($0.0001 per page), gated by
   the budget reserve. Results cache in
   `openalex_publishers`, so only a fresh install pays for the full
   ~16k-host sweep once.
7. `embed_journals` last. It re-embeds journals from the stats-built text,
   and on CPU it is the slow step of the wave, at about 45 minutes for a
   full run. It streams the journal rows through a server-side cursor and
   caps each model call at 256 times the square of the call's longest
   text in tokens (attention cells), because ONNX Runtime's memory arena
   only grows: uncapped 256-journal calls took the old job past 3 GB and
   the scheduler's 2 GB limit killed it before it stored a row. The capped
   calls keep a full run near 650 MB and produce the same vectors.

A failed stage prints `wave: <stage> failed` and does not stop the wave: the
stages that read its output are skipped, and with them every stage that
reads theirs (the log names each one); all other stages still run, and
the wave exits with code 1 after printing its failed stages and the
command that resumes it. Both waves work this way; see "Nightly
scheduler" for the alert. `--from STAGE` starts at the named stage and
runs it and everything after it; stage names match the `backend/jobs/`
script names, and an unknown name exits with code 2 and prints the
valid list:

```bash
bash scripts/refresh_wave.sh --from harvest_openalex_funders
```

Each stage prints a stats summary as JSON to stdout when it finishes, and
tracebacks go to stderr. Five stages also record runs in the `harvest_runs`
table, which the admin panel's run history lists: `harvest_stats`,
`resolve_author_ids`, `harvest_oa_colors`, `harvest_work_funders`, and
`embed_journals`. The wave keeps no log file of its own, so pipe the output
through `tee` when you want a record:

```bash
bash scripts/refresh_wave.sh 2>&1 | tee wave.log
```

`harvest_stats` and `backfill_pure_authors` cover the default institution
only. `resolve_author_ids` and `build_openalex_works` cover every active
institution. On a multi-institution deployment, run the first pair with
`--institution <code>` for each additional institute after the wave.

## Weekly source wave

The nightly wave only derives from stored data plus $0 OpenAlex
singletons. The sources that create works and coverage — Pure, the deal
sources, OpenAPC, DOAJ, JISC — would otherwise run at bootstrap only, so a
filled database freezes in steady state.
`backend/scripts/source_wave.sh` refreshes them once a week, per active
institution, in bootstrap DAG order:

```bash
cd backend
bash scripts/source_wave.sh
```

Every job is idempotent, so rerunning the wave or any stage is safe. A
failing stage does not stop the wave (the nightly wave's rule, above), and
`--from STAGE` runs that stage and every later one. STAGE is a stage name
(`deals-reconcile`, `openapc`, `pure:rug`, `stats:rug`) or a job script name
with or without `.py` (`reconcile`, `harvest_doaj.py`); the script prints
the full list when the name is unknown. The stages, in order:

1. Global deal and reference sources, in bootstrap GLOBAL_STEPS order:
   `scrape_openaccess_nl`, `ingest_jct`, `ingest_oaforward`, `reconcile` (publisher-pattern
   coverage re-derives here, so new journals join their deal; needs the two
   deal sources), `backfill_issn_l` (needs `reconcile`; the OpenAIRE match
   needs it), `ingest_openapc`, `harvest_doaj`, `harvest_jisc`.
2. Per institution, in bootstrap INST_STEPS order: `harvest_pure`
   (incremental current-year sweep), `harvest_pure --cerif`,
   `harvest_pure_entities`, `enrich_works` (all need `harvest_pure`),
   `harvest_openaire`, `derive_openaire_facts` (needs the OpenAIRE match).
3. `backfill_flags` once (works_2020_plus / last_active_year recompute over
   the fresh corpus), then `harvest_stats --institution` per institution
   (needs that institution's enrichment, OpenAIRE and facts stages, and
   `openapc` and `flags`).

Only free routes run here by design. The Pure sweep reads the institution's
OAI endpoint, the deal sources are two scrapes plus local ingests, DOAJ and
OpenAPC are CSV downloads, and JISC skips cleanly without
`JB_JISC_API_KEY`. The one OpenAlex consumer, `harvest_stats`, gates on
`openalex_budget_ok()` and stops below the budget reserve. Enrichment
and the OpenAIRE match use $0 single-entity GETs.

The `scheduler` service runs the wave Sunday 22:00 UTC (override with
`JB_SOURCE_WAVE_CRON`), ahead of the Monday 01:30 nightly wave so both fit
in one weekend night. A rerun of the wave is harmless any day.

### Data freshness

`GET /api/v1/{inst}/meta/freshness` reports, for one institution, when
each data source last refreshed successfully and whether that is still on
schedule. Three places show it:

- The About page (`/{inst}/about#data-freshness`) has one row per source:
  what it provides, the last successful refresh with its age, the schedule
  it is expected on, and a status (up to date, overdue, or refresh failed).
  From the `md` breakpoint up it is a table; on phones each source is a card.
- The footer of every institution page says "Data updated {date}". That is
  the older of the two core sources, Pure and the OpenAlex publication
  counts, and it links to the table.
- The admin Operations card lists the failed and overdue sources first,
  then the full table for every active institution.

The rules are in `backend/src/journal_browser/services/freshness.py`, and
the two wave scripts point back to it:

- `SOURCES` lists each source with its schedule and the `harvest_runs` rows
  (source and entity type) or table column that record a refresh. When a
  stage moves between the waves, move its `SOURCES` entry with it.
- `EXPECTED` gives each schedule its interval and slack. A source is
  **overdue** when its last success is older than 1 day plus 12 hours
  (nightly) or 7 days plus 1 day (weekly). A job that is in neither wave
  runs by hand and is never overdue. One source overrides the default: ROR
  records no run and refreshes only records older than 30 days, so its
  newest `updated_at` stands in for a success and a week is expected.
- A source is **failed** when the newest run of any of its parts failed.
  A run still marked `running` 24 hours after it started (`ORPHAN_AFTER`)
  counts as failed, because a killed process cannot close its row. Failed
  outranks overdue.
- A source with several parts is as old as its oldest part. It counts as
  loaded only once every part has succeeded.
- The nightly wave runs some stages for the home institution only. For the
  other institutions those sources follow the schedule in `elsewhere`.
- `public=False` keeps a source out of the public table. The admin card
  still lists it. This covers the Jisc Open Policy Finder landing, whose
  normalisation step is in neither wave.

## Nightly scheduler

The `scheduler` service runs the same backend image as the API, with
supercronic (v0.2.51, checksum-verified in `backend/Dockerfile`) executing
`backend/scripts/crontab`:

- `0 22 * * 0` — `backend/scripts/source_wave.sh`, the weekly source wave
  (see above). All its stages are free routes or self-gating, so its time
  only matters for staying ahead of the nightly wave.
- `30 1 * * *` — `backend/scripts/refresh_wave.sh`, the daily refresh wave
  (see above). Starts just after the 00:00 UTC OpenAlex credit reset so
  the credit-priced stages run on a fresh budget; they stop at the
  reserve, so nothing breaks when the wave runs at another time.
- `0 4 * * *` — `backend/scripts/backup.sh`, the nightly database backup
  (see below).

All schedules are UTC and overridable from `.env` (`JB_SOURCE_WAVE_CRON`,
`JB_REFRESH_WAVE_CRON`, `JB_BACKUP_CRON`); changing them needs a scheduler
restart (`docker compose up -d scheduler`). Job output lands in the
container log:

```bash
docker compose logs scheduler
```

Run a job by hand through the same service. The waves need bash, so pass it
as the entrypoint:

```bash
docker compose run --rm --entrypoint /bin/bash scheduler /app/scripts/refresh_wave.sh
docker compose run --rm --entrypoint /bin/bash scheduler /app/scripts/source_wave.sh --from enrich:ut
docker compose run --rm --entrypoint /bin/sh scheduler /app/scripts/backup.sh
```

Both waves end by running `backend/scripts/prewarm.py`, which requests the
first pages a visitor reaches for every active institution, so cold
Postgres pages and in-process caches are filled before anyone visits. Run
it by hand after a redeploy or before a demo:

```bash
docker compose exec scheduler uv run --no-dev python scripts/prewarm.py
```


### Alerts and recovery

A wave must not die unnoticed. On 2026-11-22 a redeploy recreated the
scheduler in the middle of the source wave: the rest of the wave never ran
and nothing reported it. Three mechanisms in `backend/scripts/lib.sh` cover
that:

- **Failure alerts.** With `JB_ALERT_WEBHOOK_URL` set, a failing stage, a
  failing backup and a wave that could not start POST one JSON message,
  `{"text": "..."}`, to that URL. A Slack or Mattermost incoming webhook
  takes the body as is. The text names the host (`JB_ALERT_HOST`, else the
  container hostname), the job, the stage that failed and the command that
  resumes it. Without the URL the same line is only logged.
- **Dead waves.** A wave writes the stage it is about to run to
  `backend/landing/waves/<wave>.state` and removes the file when it exits.
  A wave killed before that (SIGKILL, the OOM killer, a container recreate)
  leaves the file, and the next scheduler start or wave start reports it
  with the resume command: from the first stage that failed, or else from
  the stage that was running. A wave that still runs holds
  `waves/<wave>.lock`; it is left alone, and a second copy of the same wave
  refuses to start.
- **Heartbeat.** With per-job `JB_HEARTBEAT_REFRESH_URL`,
  `JB_HEARTBEAT_SOURCE_URL`, `JB_HEARTBEAT_BACKUP_URL`, or the fallback
  `JB_HEARTBEAT_URL` set, each wave and the backup send one GET after ending
  well, as a healthchecks.io check expects. Nothing pings while the scheduler
  is down or a job never starts, so the check goes late there.

The scheduler start and the start of each wave also run
`jobs/reap_orphaned_runs.py`: harvest runs that a killed process left
`running` become `failed`, with `{"error": "orphaned: process gone at
<timestamp>"}` in their stats. A run whose process still holds its lock
(`backend/landing/run-locks/<run id>.lock`) is left alone.

## Backups and restore

`backend/scripts/backup.sh` takes a shared lock (`flock -s -w 7200`,
overridable via `JB_BACKUP_LOCK_WAIT`) on `refresh_wave.lock` so an
overlapping nightly wave finishes before `pg_dump` starts, then runs
`pg_dump --format=custom --compress=zstd:9` into
`./backups/journalbrowser-<UTC timestamp>.dump`
(an estimated 6.5 GB on a full instance; with pg_dump's default gzip the
live archives were about 10 GB), followed by a `pg_restore --list` sanity
check on the archive and pruning to the newest `JB_BACKUP_KEEP` (default 7)
dumps. The backend image installs `postgresql-client-17` from the PGDG apt
repo, so the dump client always matches the db service's Postgres major,
and its `pg_dump` and `pg_restore` read and write zstd. The first
`mkdir backend/state`-style fresh-host cases are handled by the bootstrap
service, which hands the root-owned `./backups` bind mount to uid 1000.

Run a backup on demand:

```bash
docker compose run --rm --entrypoint /bin/sh scheduler /app/scripts/backup.sh
```

Why zstd:9. A 1.16 GB sample of the live `source_records` JSONB (63,099
rows), dumped into the test Postgres with the scheduler image's `pg_dump`
17.12, three runs per setting, gave:

| Compression | Archive | Share of the gzip archive | Dump | Decompress |
|---|---|---|---|---|
| none | 1,173 MB | 742% | 15.4 s | 0.3 s |
| gzip:6, the pg_dump default | 158 MB | 100% | 18.0 s | 2.65 s |
| zstd:3 | 130 MB | 82% | 15.2 s | 0.73 s |
| zstd:6 | 113 MB | 72% | 15.1 s | 0.64 s |
| zstd:9 | 104 MB | 66% | 15.4 s | 0.59 s |

The dump time barely moved: Postgres produced the JSONB text at about
75 MB/s, and pg_dump compresses while it waits for the server, so only
gzip:6 cost extra time (2.6 s per 1.16 GB here). The live nightly dump
takes about 18 minutes; expect the same duration and an archive near
6.5 GB. That size is an extrapolation: the sample is `source_records`
only. Decompression is 4.5 times faster than gzip's, but a real restore
spends its time building tables and indexes, so it saves little there.
Archives written before the switch (gzip) still restore with the same
commands.

Restore drill — prove an archive reads back, without touching the live
database (the scheduler container has `pg_restore` and the `./backups`
mount; the scratch database lives on the running db service):

```bash
docker compose exec db createdb -U journal restore_check
docker compose run --rm scheduler \
    pg_restore --no-password --exit-on-error \
    -d postgresql://journal:journal@db:5432/restore_check \
    /backups/journalbrowser-<timestamp>.dump
docker compose exec db psql -U journal -d restore_check -c \
    "SELECT count(*) FROM journals;"
docker compose exec db dropdb -U journal restore_check
```

The drill above restores into the live database service, so it adds a
full copy (about 30 GB) to the live volume and loads production for the
whole restore. To keep the live database untouched, restore into a
throwaway container of the same image instead:

```bash
docker run -d --name jb-restore-drill --memory 2g \
    -e POSTGRES_USER=journal -e POSTGRES_PASSWORD=journal -e POSTGRES_DB=restore_check \
    -v "$PWD/backups/journalbrowser-<timestamp>.dump:/dump/db.dump:ro" journal-browser-db
docker exec jb-restore-drill pg_restore -U journal -d restore_check --no-owner -j 2 /dump/db.dump
docker exec jb-restore-drill psql -U journal -d restore_check -c "SELECT count(*) FROM journals;"
docker rm -f jb-restore-drill
```

Last drill: 2026-11-25, archive `journalbrowser-20261125-040000.dump`
(6.2 GB, zstd). The restore took 53 minutes with a 2 GB memory cap and
two jobs, produced a 30 GB database at migration head, and matched live
row counts on journals, works, deals, deal_journals, source_records,
openalex_works, harvest_runs and authors. Most of the time goes to
copying `source_records`; pruning it (see [source_records retention](#source-records-retention))
shortens the restore accordingly.

Disaster recovery: bring up only `db` on a fresh pgdata volume, recreate
the database, and restore the same way before starting `backend`
(schema is inside the custom-format archive; no migrations needed):

```bash
docker compose up -d db
docker compose exec db createdb -U journal journalbrowser
docker compose run --rm scheduler \
    pg_restore --no-password --exit-on-error \
    -d postgresql://journal:journal@db:5432/journalbrowser \
    /backups/<newest archive>.dump
docker compose up -d
```

The nightly dump stays on the same disk as the database. Copy at least one
archive off-machine; an off-host target is a known open decision.

## Query statistics

The `db` service preloads `pg_stat_statements`: compose starts Postgres with
`shared_preload_libraries=pg_stat_statements` and
`pg_stat_statements.track=top`, so only the statements clients send are
counted, not those inside functions. Migration `0005_pg_stat_statements`
creates the extension; it skips that step on a server that does not preload
the library (CI). On an instance that predates the setting, check the
library is loaded, then create the extension by hand:

```sql
SHOW shared_preload_libraries;  -- must list pg_stat_statements
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
```

Postgres 17 keeps the counters across a clean restart of the db container
and loses them on a crash. The statements that used the most time, with the
first 100 characters of each:

```sql
SELECT calls,
       round(total_exec_time::numeric) AS total_ms,
       round(mean_exec_time::numeric, 1) AS mean_ms,
       rows,
       left(query, 100) AS query
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 20;
```

`queryid` identifies a statement across readings, so compare two readings
around a change. To start over, `SELECT pg_stat_statements_reset(0, 0, 0,
false);` clears every counter of every database.

## Maintenance

- **Re-harvest on demand:** every job is a standalone script under
  `backend/jobs/`; run any of them through the bootstrap image (see
  First boot variants). `JB_BOOTSTRAP=always` reruns the full pipeline.
- **After hand-fixing a deal** (alias, participation, merge): rerun
  `jobs/reconcile.py`. It re-derives, re-merges, refreshes coverage flags,
  and rewrites the curation report.
- **Updating Scimago quartiles:** drop `export_<year>.csv` into
  `backend/landing/scimagojr/` (the compose bind mount) and rerun
  `jobs/ingest_scimagojr.py`. `backend/data/` holds the tracked first-boot
  seeds only; a CSV dropped there is never read.
- **Importing the ut-metadata corpus (Twente):** with `JB_UT_METADATA_DSN`
  set, `jobs/oneoff/import_utmetadata_works.py` copies every canonical work that
  maps to a Pure uuid into `works` — the full year range without a
  re-harvest — refreshes the stats and journal flags, and widens the
  institution's data window to the oldest stored work. Idempotent; canonical
  works without a Pure uuid stay out (they still surface on journal pages
  through the live merge). `jobs/oneoff/import_utmetadata_raw.py` then copies the
  verbatim OpenAlex / OpenAIRE / Pure / Crossref work records behind that
  corpus into `source_records`, reconfirms OpenAIRE DOI identities, and
  rebuilds the OpenAlex per-journal/year OA stats window-bounded — so
  year charts and FWCI/citation metrics cover the whole data window, not
  just the years the live harvests ran.
- **Logs and request tracing:** every API request carries an id — send an
  `X-Request-ID` header (or read the one echoed back on each response) and
  grep `docker compose logs` for it to follow a single request across log
  lines. Set `JB_LOG_FORMAT=json` in `.env` for one JSON object per line
  when shipping logs to a collector. Credential-looking substrings
  (`password=`, `token=`, Bearer headers) are redacted from the output.
- **Upgrading the stack:** `git pull && docker compose up -d --build`. The
  bootstrap service applies pending migrations. Databases created before the
  migration history was squashed (2026-11) sit at revision `0069` and must
  be re-stamped once — see "Migrations" below. Fresh databases get the
  single `0001_baseline` migration, whose semantic-search index builds an
  HNSW graph and needs a few minutes plus about 100 MB of Postgres shared
  memory (compose sets `db.shm_size: 512mb`; raise it for external
  databases). Check this file's
  changelog-worthy notes before major version bumps; new settings always
  default to the Twente values, so existing deployments keep working.

### source_records retention

`source_records` stores one row per payload version (unique on source,
entity_type, source_pk, content_hash). A re-harvest that sees a changed
payload adds a version, and nothing removed the older one, so the live
table reached 28.5 GB in November 2026 with 39% of its rows superseded.

Readers use the newest version of each key. Pure entities, OpenAlex works
and the author listings look inside one institution's harvest runs. JISC,
OpenAIRE facts, work partners, OpenAPC evidence and journal info look
across all runs. The only other dependency is
`apc_evidence.source_record_id`, which points at 297 payload rows. Two
jobs shrink the table:

1. `jobs/prune_source_records.py` deletes superseded versions. It keeps the
   newest `--keep` versions per key and institution (default 1) and never
   deletes a version that `apc_evidence` points at.
2. `jobs/strip_source_records.py` removes the keys that the ingest
   projection no longer stores (`ingest.PAYLOAD_DROP_KEYS`) from rows
   written before the projection existed.

Both jobs default to a dry run that prints rows and compressed payload
bytes per source and entity type. Run them inside the backend image, in
this order:

```bash
docker compose run --rm bootstrap uv run python jobs/prune_source_records.py  # dry run
docker compose run --rm bootstrap uv run python jobs/prune_source_records.py --apply
docker exec journal-browser-db-1 psql -U journal -d journalbrowser \
  -c "VACUUM (ANALYZE) source_records"
docker compose run --rm bootstrap uv run python jobs/strip_source_records.py  # dry run
docker compose run --rm bootstrap uv run python jobs/strip_source_records.py --apply
docker exec journal-browser-db-1 psql -U journal -d journalbrowser \
  -c "VACUUM (ANALYZE) source_records"
```

Run the prune before the strip job, because a superseded version gets
deleted instead of rewritten. `--apply` in both jobs holds row locks for
one id range (10,000 ids) at a time and never blocks readers. The space a
run frees, and the space the strip job needs for its new row versions, only
settles with the `VACUUM` that follows. Plain `VACUUM` blocks neither reads
nor writes. After these steps the table files keep their size on disk, and
about half of each file is free space that new versions reuse.

To return that space to the operating system, run `VACUUM FULL
source_records` in a quiet window. It holds an ACCESS EXCLUSIVE lock for
the whole rewrite, so API requests that read payloads wait (estimate 10 to
20 minutes for the live table), and it needs free disk space of about the
table's final size.

The weekly source wave adds new versions and ends with a
`prune-source-records` stage (`prune_source_records.py --apply`), so the
table no longer grows back; autovacuum makes the freed space reusable.

First run on live, 2026-11-25: the prune deleted 1,942,848 rows (11.1 GB
of payload) in 16 minutes, the strip took about 30 minutes, and `VACUUM
FULL` took 11 minutes. `source_records` went from 26 GB to 12 GB on disk
and the database from 30 GB to 17 GB. API requests kept answering during
the rewrite.

## Migrations

The history of the original 70-migration chain is squashed into
`0001_baseline`, followed by incremental reversible revisions (`0002` through
`0009_indexes_and_scimago_clean`, which adds `lz4` TOAST compression on
`source_records.payload`, operational indexes, rebuilt author-name trigram
index, and Scimago `"-"` cleanup).

- **Ongoing deploys:** `bootstrap` and `backend` run `uv run --no-dev alembic upgrade head` on start; every revision remains reversible via `alembic downgrade`.
- **Fresh installs:** `alembic upgrade head` applies `0001_baseline` through head.
- **Existing databases** (at `0069` from before the squash): do NOT run
  `alembic upgrade head` — the old revisions no longer exist in the repo,
  and alembic refuses to work against a version row it cannot resolve.
  Re-stamp once, with no schema change:

  ```
  cd backend && uv run alembic stamp 0001_baseline --purge
  ```

  `--purge` is required because the stored version (`0069...`) no longer
  resolves; it clears the version row, then writes `0001_baseline`. The
  schema is untouched: verified on a test database upgraded through the old
  chain to `0069`, where `stamp --purge` flipped the version to
  `0001_baseline` with all 53 public tables intact.


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
