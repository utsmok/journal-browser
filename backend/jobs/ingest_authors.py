"""Ingest one institution's authors via the source adapter.

Source selection (decision 27 degradation contract): "local" (default)
builds everything from journal-browser's own harvests (pure entities +
org tree + CERIF author lists + openalex works store + resolved
identities) and works on any institution with no DSN. "utmd" opts into
the ut-metadata Postgres accelerator (institutions.external_works_dsn, or
the global JB_UT_METADATA_DSN fallback) — the UT cross-check path.

uv run python jobs/ingest_authors.py [--institution rug] [--source local|utmd]
"""

import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.authors import (
    fetch_local_source,
    fetch_source,
    ingest_authors,
)
from journal_browser.harvest.common import resolve_institution, run_harvest
from journal_browser.services import ut_metadata as ut_metadata_service


def resolve_dsn(institution) -> str | None:
    """Per-institution DSN first, global ut-metadata setting as fallback."""
    return institution.external_works_dsn or get_settings().ut_metadata_dsn or None


def select_source(institution, override: str | None) -> str:
    """'local' (default setting) or 'utmd'; the flag wins over the setting."""
    mode = (override or get_settings().author_source or "local").lower()
    if mode not in ("local", "utmd"):
        raise SystemExit(f"invalid --source {mode!r}: local|utmd expected")
    if mode == "utmd" and not resolve_dsn(institution):
        raise SystemExit(
            f"authors[{institution.code}]: --source utmd but no DSN configured "
            "(institutions.external_works_dsn / JB_UT_METADATA_DSN)"
        )
    return mode


async def run(session, institution, source_override: str | None = None) -> bool:
    mode = select_source(institution, source_override)
    if mode == "utmd":
        source = "ut-metadata"
        data = await fetch_source(ut_metadata_service._get_engine(resolve_dsn(institution)))
    else:
        source = "local"
        data = await fetch_local_source(session, institution)
    stats = await run_harvest(
        source,
        "authors",
        f"inst:{institution.code}",
        {"source": source},
        lambda _ingest: ingest_authors(session, institution.id, data, institution.ror),
        session,
        institution_id=institution.id,
    )
    print(f"authors[{institution.code}] via {source}: {json.dumps(stats)}")
    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--institution", default=None, help="institution code (default: env)")
    parser.add_argument(
        "--source",
        default=None,
        help="author data source: local (default) or utmd (DSN accelerator)",
    )
    args = parser.parse_args()

    async def main() -> None:
        engine = create_async_engine(get_settings().database_url)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            institution = await resolve_institution(session, args.institution)
            await run(session, institution, args.source)
        await engine.dispose()

    asyncio.run(main())
