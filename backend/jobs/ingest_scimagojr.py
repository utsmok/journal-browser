"""Scimagojr yearly export ingest (files must exist in the landing store).

Usage: uv run python jobs/ingest_scimagojr.py [year ...]   # default: 2024 2023 2022
"""

import asyncio
import datetime as dt
import json
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.denorm import refresh_quartiles
from journal_browser.harvest.scimagojr import ingest_year


async def main() -> None:
    # SCImago exports land a year behind, so default to the three most
    # recent completed years instead of a list that goes stale.
    this_year = dt.date.today().year
    years = [int(a) for a in sys.argv[1:]] or [this_year - 1, this_year - 2, this_year - 3]
    landing = Path(get_settings().landing_dir)
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    results = []
    for year in years:
        async with maker() as session:
            results.append(await ingest_year(session, year, landing))
    async with maker() as session:
        await refresh_quartiles(session)
        await session.commit()
    await engine.dispose()
    print(json.dumps(results))


if __name__ == "__main__":
    asyncio.run(main())
