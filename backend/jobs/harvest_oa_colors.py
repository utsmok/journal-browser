"""Sample recent works per OpenAlex-OA journal to observe its OA color.

Usage: uv run python jobs/harvest_oa_colors.py [--limit N]

Fills journals.oa_status_observed for venues flagged is_oa without DOAJ
membership or price evidence. Fills NULLs only, so it is resumable and
cheap to rerun after journal sweeps.
"""

import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.journal_oa import harvest_oa_statuses


async def main() -> None:
    import sys

    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        stats = await harvest_oa_statuses(session, limit=limit)
        await session.commit()
    await engine.dispose()
    print(json.dumps(stats))


if __name__ == "__main__":
    asyncio.run(main())
