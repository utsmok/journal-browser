"""Harvest OpenAIRE research products for one institution.

uv run python jobs/harvest_openaire.py                          # default institution
uv run python jobs/harvest_openaire.py --institution rug        # by code
uv run python jobs/harvest_openaire.py --limit 200
"""

import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.common import resolve_institution
from journal_browser.harvest.openaire import harvest_openaire_products


async def main(session, institution, limit: int | None) -> None:
    stats = await harvest_openaire_products(session, institution, limit=limit)
    print(json.dumps(stats, indent=1, default=str))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--institution", default=None, help="institution code (default: env)")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    async def run() -> None:
        engine = create_async_engine(get_settings().database_url)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            await main(session, await resolve_institution(session, args.institution), args.limit)
        await engine.dispose()

    asyncio.run(run())
