"""Institution statistics harvest (2020+ window, collect-only).

Usage: uv run python jobs/harvest_stats.py [limit]
"""

import asyncio
import json
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.common import get_home_institution
from journal_browser.harvest.denorm import refresh_home_stats
from journal_browser.harvest.institution_stats import (
    harvest_institution_stats,
    write_pure_canon_stats,
)


async def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        stats = await harvest_institution_stats(session, limit=limit)
        home = await get_home_institution(session)
        stats["pure_canon_rows"] = await write_pure_canon_stats(session, home.id)
        await refresh_home_stats(session)
        await session.commit()
    await engine.dispose()
    print(json.dumps(stats))


if __name__ == "__main__":
    asyncio.run(main())
