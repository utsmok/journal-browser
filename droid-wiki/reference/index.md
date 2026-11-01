# Reference

Lookup material for operating and extending journal-browser: every
configuration knob, the database schema, and the dependency inventory. For
narrative explanations, start at [Architecture](../overview/architecture.md)
and [Data model](../systems/data-model.md); this section is the terse,
complete version of each topic.

## Pages

- [Configuration](configuration.md): every environment variable from
  `.env.example` with defaults and behavior, plus the admin-editable
  `backend/settings.yaml` overlay and its masking rules.
- [Data models](data-models.md): all 34 tables derived from
  `backend/src/journal_browser/models/`, grouped into shared core,
  per-institution, and bookkeeping, with key columns and constraints.
- [Dependencies](dependencies.md): backend and frontend libraries with a
  one-line purpose each, the external data services the harvest pipeline
  calls, and the toolchain version requirements.

## When to use each

- Deploying a new instance or retuning an existing one: read
  [Configuration](configuration.md). Institution defaults fit a Twente
  deployment; the identity levers are what you change first.
- Writing queries, migrations, or new models: read
  [Data models](data-models.md) for the table map, then the explanatory
  page for denormalization and identity semantics.
- Debugging a failed harvest or evaluating a new library: read
  [Dependencies](dependencies.md) together with
  [Harvest sources](../systems/data-pipeline/harvest-sources.md), which
  maps each external service to the jobs that call it.

Frontend-facing behavior (search, admin UI, per-institution pages) is
covered in the [apps](../apps/index.md) section rather than here.
