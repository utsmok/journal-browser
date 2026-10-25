"""Scimagojr yearly export ingest (files must exist in the landing store).

Missing exports are materialized from the tracked seeds in backend/data/
(scimagojr.com sits behind Cloudflare, so the CSVs cannot be downloaded).

Usage: uv run python jobs/ingest_scimagojr.py [year ...]   # default: 2024 2023 2022
"""

import asyncio
import datetime as dt
import gzip
import json
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.denorm import refresh_quartiles
from journal_browser.harvest.scimagojr import ingest_year

SEED_DIR = Path(__file__).resolve().parent.parent / "data" / "scimagojr"


def materialize_seed(year: int, landing: Path) -> None:
    """Expand a tracked seed export into the landing store on first use."""
    target = landing / f"export_{year}.csv"
    if target.exists():
        return
    seed = SEED_DIR / f"export_{year}.csv.gz"
    if seed.exists():
        target.write_bytes(gzip.decompress(seed.read_bytes()))


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
        materialize_seed(year, landing)
        async with maker() as session:
            results.append(await ingest_year(session, year, landing))
    async with maker() as session:
        await refresh_quartiles(session)
        await session.commit()
    await engine.dispose()
    print(json.dumps(results))


if __name__ == "__main__":
    asyncio.run(main())
