"""Harvest OpenAIRE research products for the institution.

uv run python jobs/harvest_openaire.py             # full sweep
uv run python jobs/harvest_openaire.py --limit 200
"""

import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.openaire import harvest_openaire_products


async def main(session, limit: int | None) -> None:
    stats = await harvest_openaire_products(session, limit=limit)
    print(json.dumps(stats, indent=1, default=str))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    async def run() -> None:
        engine = create_async_engine(get_settings().database_url)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            await main(session, args.limit)
        await engine.dispose()

    asyncio.run(run())
