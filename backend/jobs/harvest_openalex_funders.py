"""OpenAlex funder harvest -> openalex_funders.

Usage: uv run python jobs/harvest_openalex_funders.py [--refresh]

Default: gap-fill works-linked funder ids the table lacks ($0
singleton GETs). --refresh re-fetches every stored funder instead, for
upstream corrections such as the 2026-11 citation re-matcher.
"""

import asyncio
import json
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.funders import harvest_openalex_funders, refresh_openalex_funders


async def main() -> None:
    refresh = "--refresh" in sys.argv
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        stats = (
            await refresh_openalex_funders(session)
            if refresh
            else await harvest_openalex_funders(session)
        )
        await session.commit()
    await engine.dispose()
    print(json.dumps(stats))


if __name__ == "__main__":
    asyncio.run(main())
