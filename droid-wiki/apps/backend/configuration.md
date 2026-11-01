# Configuration

Active contributors: utsmok

Configuration flows through three layers: `JB_*` environment variables parsed
by pydantic-settings, a live-reloaded YAML overlay that the admin panel
writes, and the per-institution rows in the `institutions` table that the
global settings only seed. The code lives in
`backend/src/journal_browser/config.py` and
`backend/src/journal_browser/settings_schema.py`. Runtime behavior around
the admin settings endpoints is in [API surface](api-surface.md) and
[Admin panel](../../features/admin.md); this page covers the mechanism.

## Directory layout

```text
backend/
├── settings.yaml.example   # commented template for the overlay (tracked)
├── settings.yaml           # deployed overlay (bind-mounted, untracked)
└── src/journal_browser/
    ├── config.py           # Settings model, YAML merge, live reload
    └── settings_schema.py  # FieldDef registry for the admin settings API
```

Environment variables also arrive untracked through `.env` and the
`environment:` blocks in `docker-compose.yml`.

## Key abstractions

| Name | File path | One-line description |
|---|---|---|
| `Settings` | `backend/src/journal_browser/config.py` | pydantic-settings model over `JB_*` env vars with `.env` support and `populate_by_name` |
| `get_settings` | `backend/src/journal_browser/config.py` | Cached accessor that merges the YAML overlay and reloads on mtime change |
| `load_settings_yaml` | `backend/src/journal_browser/config.py` | Reads the overlay doc, `{}` when missing; YAML syntax errors raise |
| `reset_settings_cache` | `backend/src/journal_browser/config.py` | Drops the cache after the admin PUT writes the file (and in tests) |
| `EXCLUDED_WORK_TYPES` | `backend/src/journal_browser/config.py` | Work types (preprints, books) kept out of every count, with `normalize_work_type` |
| `FieldDef` | `backend/src/journal_browser/settings_schema.py` | One admin-editable knob: key, section, type, label, help, default |
| `SETTINGS_REGISTRY` | `backend/src/journal_browser/settings_schema.py` | The ordered list of `FieldDef` entries served by `GET /admin/settings` |
| `INSTITUTION_KEYS` | `backend/src/journal_browser/settings_schema.py` | The 13 settings that live in the institutions table, not the global overlay |
| `value_for_response` | `backend/src/journal_browser/settings_schema.py` | Masks secret values as `********` (unset secrets read as `null`) |

## How it works

### Layer 1: environment

`Settings` in `backend/src/journal_browser/config.py` is a
`pydantic_settings.BaseSettings` with `env_prefix="JB_"`, `env_file=".env"`,
and `extra="ignore"`. Notable fields: `database_url` (default
`postgresql+asyncpg://journal:journal@localhost:5433/journalbrowser`),
`ut_metadata_dsn` (empty means the accelerator feature is off), `admin_password`
(empty disables the admin panel), `cors_origins`, the Pure OAI-PMH endpoint
and pacing, the data window (`data_window_start` 2020, `data_window_end` open),
`bootstrap` mode (`auto`/`always`/`off`), and `author_source` (`local` or
`utmd`). Two fields accept unprefixed aliases via `AliasChoices`:
`openalex_api_key` also reads `OPENALEX_API_KEY`, and `contact_email` also
reads `CONTACT_EMAIL`. The `institution_*` fields are first-boot seeds: the
validator on `institution_code` enforces `[a-z0-9-]+`, and the properties
`window_years` and `ror_id` derive the harvest window and the ROR slug.

The module also hosts a serving policy that is configuration in spirit:
`normalize_work_type` collapses bare and `info:eu-repo/semantics/`-prefixed
work-type spellings, and `work_type_excluded` tests membership in
`EXCLUDED_WORK_TYPES` (`preprint`, `postedcontent`, `workingpaper`, `book`,
`bookchapter`, `bookpart`, `monograph`), keeping non-journal output out of
every count and stat.

### Layer 2: the settings.yaml overlay

`get_settings()` builds a base `Settings` from the environment, loads the
overlay from `settings.yaml` (path override: `JB_SETTINGS_YAML`), merges
`{**base.model_dump(), **overlay}`, and revalidates into a cached `Settings`.
The cache keys on the file's mtime, so an admin edit lands without a restart.
Two failure behaviors are deliberate: a YAML syntax error raises instead of
being silently dropped, and a truncated mid-write file keeps the last good
overlay because the mtime is pinned only after a successful validate. The
admin settings `PUT` writes this file and calls `reset_settings_cache()`.
`backend/settings.yaml.example` documents every key, including the YAML
caution to quote `yes`/`no`/`on`/`off` values.

One setting is not live: `cors_origins` is applied when
`backend/src/journal_browser/main.py` builds the app, so changing it needs a
container restart. Two levers are environment-only and never appear in the
overlay or the registry: `JB_SKIP_EMBEDDING_WARMUP` and `JB_DOCS_DIR`.

### Layer 3: the settings registry and the institutions table

`backend/src/journal_browser/settings_schema.py` declares one `FieldDef` per
admin-editable knob in `SETTINGS_REGISTRY`, with `section` either `global`
(served and edited by `GET`/`PUT /api/v1/admin/settings`, backed by
`settings.yaml`) or `institution` (rendered on each university's admin page
and stored in the `institutions` table via `GET`/`PUT /api/v1/admin/institutions/{code}`).
Defaults come from `Settings.model_fields`, so the registry cannot drift from
the settings model. The four secrets (`admin_password`, `openalex_api_key`,
`jisc_api_key`, `ut_metadata_dsn`) are masked by `value_for_response`: unset
reads as `null`, set reads as `********`, and `PUT`ting `""` or `********`
keeps the current value so the panel never echoes a secret.

`database_url` is deliberately absent from the registry: the boot dependency
must not be editable at runtime. The institution-section keys
(`institution_code`, `institution_name`, `institution_short`,
`institution_ror`, `institution_openalex_id`, `openaire_org_id`,
`data_window_start`, `data_window_end`, `library_url`, `oa_guide_url`,
`support_email`, `admin_contact`, `research_portal_url`) seed the default
institutions row on first boot; afterwards that row is authoritative, which is
what lets one deployment host several universities (see
[Multi-institution core](../../features/multi-institution.md)).

```mermaid
graph TD
    ENV["JB_* env vars + .env"] --> BASE["Settings (base)"]
    YAML["backend/settings.yaml overlay"] --> GETS["get_settings()"]
    BASE --> GETS
    GETS --> CACHE["Cached merged Settings<br/>(mtime-keyed reload)"]
    CACHE --> APP["App + CORS at startup"]
    CACHE --> RT["Routers and services"]
    CACHE --> JOBS["Harvest jobs"]
    ADM["Admin panel"] -->|PUT /admin/settings| YAML
    ADM -->|PUT /admin/institutions/&#123;code&#125;| INST[("institutions table")]
    INST -.->|authoritative after first boot| RT
```

### Feature flags

`enable_journal_citations` and `enable_jisc` (env `JB_ENABLE_JOURNAL_CITATIONS`,
`JB_ENABLE_JISC`) default to `false` and stay off until explicitly enabled.
Both are registered in `SETTINGS_REGISTRY` as global bools, so an operator can
flip them in the admin panel as well as the environment, and their scaffolds
in the routers and frontend check them before exposing anything.

## Integration points

- **Admin panel**: the settings editor renders `SETTINGS_REGISTRY` (labels,
  help text, types, masked secrets); see [Admin panel](../../features/admin.md).
- **Institution scoping**: the institution-section keys bridge global config
  and the per-university rows; see
  [Multi-institution core](../../features/multi-institution.md).
- **Harvest jobs**: `backend/jobs/bootstrap.py` and every job read the same
  cached `get_settings()`, so overlay edits change harvest behavior too; the
  pipeline is in [Data pipeline](../../systems/data-pipeline/index.md).
- **Deployment**: which env vars a compose deployment sets is documented in
  `DEPLOYMENT.md` and the `environment:` blocks of `docker-compose.yml`.

## Entry points for modification

Adding a setting means three edits: declare the field on `Settings` in
`backend/src/journal_browser/config.py`, add a matching `_f(...)` entry to
`SETTINGS_REGISTRY` in `backend/src/journal_browser/settings_schema.py` (pick
the section by where the value should live), and document the key in
`backend/settings.yaml.example`. Secrets must be added to the `_SECRETS`
tuple to get masking. Values that need code beyond a plain field, such as the
work-type exclusions, belong next to `Settings` as module-level helpers so
both the app and the jobs import them from one place.

## Key source files

| File | Role |
|---|---|
| `backend/src/journal_browser/config.py` | `Settings`, overlay merge with live reload, work-type policy |
| `backend/src/journal_browser/settings_schema.py` | `FieldDef` registry, section split, secret masking |
| `backend/settings.yaml.example` | Commented template for the deployed overlay |
| `backend/src/journal_browser/routers/admin/settings_admin.py` | `GET`/`PUT /admin/settings` over the registry and overlay file |
| `backend/src/journal_browser/routers/admin/__init__.py` | Admin router composition (order documented in the module docstring) |
