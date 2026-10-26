"""Ingest one institution's authors from the external canonical-works DB.

Reads the ut-metadata-style Postgres (institutions.external_works_dsn, or
the global JB_UT_METADATA_DSN fallback) and fills authors / author_works.
No DSN configured: logs a skip line and exits 0, so bootstrap on
deployments without author data never fails.

uv run python jobs/ingest_authors.py [--institution rug]
"""

import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.authors import ingest_authors
from journal_browser.harvest.common import resolve_institution, run_harvest
from journal_browser.services import ut_metadata as ut_metadata_service


def resolve_dsn(institution) -> str | None:
    """Per-institution DSN first, global ut-metadata setting as fallback."""
    return institution.external_works_dsn or get_settings().ut_metadata_dsn or None


async def run(session, institution) -> bool:
    dsn = resolve_dsn(institution)
    if not dsn:
        print(f"authors: no ut-metadata DSN for {institution.code}; skipping")
        return False
    engine = ut_metadata_service._get_engine(dsn)
    stats = await run_harvest(
        "ut-metadata",
        "authors",
        f"inst:{institution.code}",
        {"source": "ut-metadata"},
        lambda _ingest: ingest_authors(session, institution.id, engine),
        session,
        institution_id=institution.id,
    )
    print(f"authors[{institution.code}]: {json.dumps(stats)}")
    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--institution", default=None, help="institution code (default: env)")
    args = parser.parse_args()

    async def main() -> None:
        engine = create_async_engine(get_settings().database_url)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            institution = await resolve_institution(session, args.institution)
            await run(session, institution)
        await engine.dispose()

    asyncio.run(main())
