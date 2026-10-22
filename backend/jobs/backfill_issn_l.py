"""Backfill deal_journals.issn_l via the issn_map; flag unresolvable rows.

Usage: uv run python jobs/backfill_issn_l.py
"""

import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.issn_backfill import backfill_deal_issn_l


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        stats = await backfill_deal_issn_l(session)
        await session.commit()
    await engine.dispose()
    print(json.dumps(stats))


if __name__ == "__main__":
    asyncio.run(main())
