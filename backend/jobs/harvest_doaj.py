"""Harvest the DOAJ journal CSV as the OA-model canon.

Usage: uv run python jobs/harvest_doaj.py

One CSV download lands verbatim, then every row denormalizes onto journals
(DOAJ APC declaration -> gold/diamond canon, journal URL -> canon
homepage). OA candidates without a match stamp doaj_in_doaj=false, so the
classification can trust the flag. Rerun freely: it is a full refresh.
"""

import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.doaj import harvest_doaj


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        stats = await harvest_doaj(session)
        await session.commit()
    await engine.dispose()
    print(json.dumps(stats))


if __name__ == "__main__":
    asyncio.run(main())
