# Systems

Active contributors: utsmok

The systems section covers the machinery behind the product: how data gets in, how it is
stored, and how it is served. Start with [Architecture](../overview/architecture.md) for the
big picture.

| Page | What it covers |
|---|---|
| [Data pipeline](data-pipeline/index.md) | The two-layer harvest DAG that fills the database from external sources, its landing zone, and its run bookkeeping. |
| [Data model](data-model.md) | The Postgres tables the pipeline writes and the API serves, plus the migration conventions that shape them. |
| [Search](search.md) | What serving reads after harvest: full-text search, facet caches, cache epochs, and pgvector semantic search. |

## Related pages

- [Backend](../apps/backend/index.md) for the API app that serves this data.
- [Design decisions](../background/design-decisions.md) for why the pipeline is shaped this way.
