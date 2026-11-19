"""OpenAIRE graph v3 funders sweep -> openaire_funders.

Usage: uv run python jobs/harvest_openaire_funders.py
"""

import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.funders import harvest_openaire_funders


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        stats = await harvest_openaire_funders(session)
        await session.commit()
    await engine.dispose()
    print(json.dumps(stats))


if __name__ == "__main__":
    asyncio.run(main())
