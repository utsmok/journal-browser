# Configuration

Every runtime knob lives in one of two layers. Environment variables
(prefixed `JB_*`) are read once at boot through
`backend/src/journal_browser/config.py`. The admin panel can also write
non-secret settings to `backend/settings.yaml`; YAML values override the
environment and reload live, with no restart. The annotated source of truth
for env vars is `.env.example`; the editable fields are declared in
`backend/src/journal_browser/settings_schema.py`.

All defaults below fit a Twente instance. To run your own institution,
change the identity levers before the first boot; the bootstrap service
seeds them into the database once, after which the `institutions` table row
is authoritative.

## Institution identity levers

Seeded into the default `institutions` row on first boot. Served to the
frontend through the meta endpoints; edited later at
`/admin/institutions/{code}`.

| Env var | Default | What it does |
|---|---|---|
| `JB_INSTITUTION_NAME` | `University of Twente` | Full institution name. |
| `JB_INSTITUTION_SHORT` | `Twente` | Short form for compact UI labels ("Twente works"). |
| `JB_INSTITUTION_ROR` | `https://ror.org/006hf6230` | ROR identifier URL; the home institution resolves by ROR, not a flag. |
| `JB_OPENAIRE_ORG_ID` | empty | `openorgs____::...` id for the OpenAIRE product harvest; empty disables the OpenAIRE harvest entirely. Find yours via the OpenAIRE organizations API by legal name. |
| `JB_PURE_OAI_BASE_URL` | `https://ris.utwente.nl/ws/oai` | Institutional-repository OAI-PMH endpoint (Twente Pure, anonymous access). |
| `JB_LIBRARY_URL` | `https://www.utwente.nl/library` | Library link shown in the UI. |
| `JB_OA_GUIDE_URL` | UT open-access guide URL | Link to the open-access publishing guide. |
| `JB_SUPPORT_EMAIL` | `open-access@utwente.nl` | Open-access support mailbox shown in the UI. |
| `JB_ADMIN_CONTACT` | `s.mok@utwente.nl` | Personal admin contact in the footer; empty hides the row. |
| `JB_RESEARCH_PORTAL_URL` | `https://research.utwente.nl` | Link to the research portal. |

## Data knobs

| Env var | Default | What it does |
|---|---|---|
| `JB_DATA_WINDOW_START` | `2020` | First publication year harvested and shown, inclusive. |
| `JB_DATA_WINDOW_END` | `0` | Last publication year, inclusive; `0` means open-ended (to now). The initial Twente deployment runs `2020/0`. |
| `JB_IGNORED_ISSNS` | empty | ISSN-Ls treated as nonexistent: excluded from search, facets, similar lists, and author venue lists; the detail page returns 404. The env form takes JSON list syntax; the settings schema documents the overlay form (one per line) as applied live. The `.env.example` comment still calls the env path a scaffold, so prefer the admin overlay. |
| `JB_CONTACT_EMAIL` | empty | Contact email sent to OpenAlex for polite-pool identification. |

## Credentials

All four are masked by the settings API
(`backend/src/journal_browser/settings_schema.py`): a set value reads back
as `********`, an empty one as `null`. They are never returned in clear
text.

| Env var | Default | What it does |
|---|---|---|
| `OPENALEX_API_KEY` | empty | Free-tier OpenAlex key, needed only for cursor-paged harvests; single-entity lookups stay keyless. `aletheca` also reads `ALETHECA_OPENALEX_API_KEY`. |
| `JB_ADMIN_PASSWORD` | empty | Password for `/admin` and the admin API; empty disables the panel. |
| `JB_JISC_API_KEY` | empty | Credentials for the JISC integration; only relevant when `JB_ENABLE_JISC` is on. |
| `JB_UT_METADATA_DSN` | empty | Optional read-only Postgres DSN for the external ut-metadata stack (canonical Twente publications). Unset, the ut-works endpoints degrade to works_stats-only. A fresh deployment does not need it. |

## Feature flags

Both flags gate feature scaffolds that ship OFF and stay OFF until you
explicitly enable them. They flow through `settings_schema.py` and the
admin settings overlay.

| Env var | Default | What it does |
|---|---|---|
| `JB_ENABLE_JOURNAL_CITATIONS` | `false` | Citation feature scaffold. |
| `JB_ENABLE_JISC` | `false` | JISC integration scaffold; pairs with `JB_JISC_API_KEY`. |

## Dev and CI skips

| Env var | Default | What it does |
|---|---|---|
| `JB_SKIP_DB_TESTS` | unset | Set to `1` to make pytest skip database tests (`JB_SKIP_DB_TESTS=1 uv run pytest -q`). |
| `JB_SKIP_EMBEDDING_WARMUP` | unset | Set to `1` to skip the ~130 MB ONNX model preload on app import; used for offline OpenAPI dumps and CI. Leave unset in deployments. |
| `JB_BOOTSTRAP` | `auto` | Bootstrap service mode: `auto` harvests only on an empty DB, `always` on every start, `off` never. |

## Other environment variables

| Env var | Default | What it does |
|---|---|---|
| `JB_DATABASE_URL` | `postgresql+asyncpg://journal:journal@localhost:5433/journalbrowser` | Asyncpg DSN for the serving database. Deliberately absent from the runtime settings overlay (see below). |
| `JB_LANDING_DIR` | `landing` | Raw landing zone for downloaded files; compose pins the bind mount to `./backend/landing`. |
| `JB_DOCS_DIR` | `docs` | Directory of the markdown docs served via the docs endpoints; compose mounts `./docs` read-only. |
| `NEXT_PUBLIC_SITE_URL` | empty | Public hostname baked into the frontend at build time; used in citation links. Set it before the first frontend build of a new instance. |

## The runtime settings overlay

The admin panel writes non-secret global settings to
`backend/settings.yaml` (bind-mounted into the backend container). Three
rules govern it:

1. YAML values override the `JB_*` variables and reload live; a restart is
   not needed. An env var only applies while the YAML lacks that key.
2. `JB_SETTINGS_YAML` (default `settings.yaml`) relocates the file.
3. `database_url` is intentionally absent from the editable schema: the
   boot dependency must not change at runtime.

CORS is the one overlay key that still needs a restart, because it applies
at startup. Secrets in the overlay are write-only through the API; reads
are masked as described above.

Global overlay keys (from the registry in
`backend/src/journal_browser/settings_schema.py`):

| Key | Type | Purpose |
|---|---|---|
| `admin_password` | secret | Admin panel password. |
| `openalex_api_key` | secret | OpenAlex harvest key. |
| `jisc_api_key` | secret | JISC credentials. |
| `contact_email` | string | OpenAlex polite-pool identification. |
| `cors_origins` | list | Browser origins allowed to call the API; restart to apply. |
| `ignored_issns` | list | ISSN-Ls excluded from the whole serving path, one per line. |
| `pure_oai_base_url` | string | Default OAI-PMH endpoint (first-boot seed). |
| `pure_oai_min_spacing` | number | Minimum seconds between OAI-PMH requests. |
| `author_source` | string | `local` (own harvests, the standalone default) or `utmd` (the ut-metadata accelerator). |
| `openalex_author_sweep_max_authors` | number | Per-run author budget for the OpenAlex works enrichment sweep; 0 disables it. |
| `landing_dir` | string | Landing zone path. |
| `curation_report_path` | string | Where the reconcile job writes its HTML curation report. |
| `bootstrap` | string | `auto`, `always`, or `off`. |
| `enable_journal_citations` | bool | Citation scaffold. |
| `enable_jisc` | bool | JISC scaffold. |

A second group of fields is institution-backed rather than global: the
registry keys `institution_code`, `institution_name`,
`institution_short`, `institution_ror`, `institution_openalex_id`,
`openaire_org_id`, `data_window_start`, `data_window_end`, `library_url`,
`oa_guide_url`, `support_email`, `admin_contact`, and
`research_portal_url` live in the `institutions` table, are seeded from the
env vars on first boot, and are edited per institution at
`/admin/institutions/{code}`. They never appear in the global values dict.

## Related pages

Deployment context and per-environment examples live in
[Backend configuration](../apps/backend/configuration.md) and
`DEPLOYMENT.md`. The multi-institution split between global and
per-institution settings is explained in
[Multi-institution](../features/multi-institution.md).
