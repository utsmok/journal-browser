"""Per-work OpenAlex funder/grant harvest -> work_funders.

Usage: uv run python jobs/harvest_work_funders.py
"""

import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.work_funders import harvest_work_funders


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        stats = await harvest_work_funders(session)
        await session.commit()
    await engine.dispose()
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
