"""Build the openalex_works store for one institution (or all hosted).

Projection over the harvested OpenAlex works payloads — no API calls.
Re-run any time; the author-ids job re-projects after its enrichment
sweep lands new works.

uv run python jobs/build_openalex_works.py [--institution rug]
"""

import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.common import get_active_institutions, resolve_institution
from journal_browser.harvest.openalex_works import rebuild_openalex_works


async def main(code: str | None = None) -> None:
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        if code:
            institutions = [await resolve_institution(session, code)]
        else:
            institutions = await get_active_institutions(session)
        stats = {}
        for institution in institutions:
            stats[institution.code or str(institution.id)] = await rebuild_openalex_works(
                session, institution
            )
        await session.commit()
    await engine.dispose()
    print(json.dumps(stats))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--institution", default=None, help="institution code (default: all)")
    args = parser.parse_args()
    asyncio.run(main(args.institution))
