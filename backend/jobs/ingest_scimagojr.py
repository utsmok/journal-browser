"""Scimagojr yearly export ingest (files must exist in the landing store).

Missing exports are materialized from the tracked seeds in backend/data/
(scimagojr.com sits behind Cloudflare, so the CSVs cannot be downloaded).

Usage: uv run python jobs/ingest_scimagojr.py [year ...]
Default: the three most recent years with a seed or landing export.
"""

import asyncio
import gzip
import json
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.denorm import refresh_quartiles
from journal_browser.harvest.scimagojr import SOURCE, ingest_year

SEED_DIR = Path(__file__).resolve().parent.parent / "data" / "scimagojr"


def materialize_seed(year: int, landing: Path) -> bool:
    """Expand a tracked seed export into the landing store on first use."""
    target = landing / SOURCE / f"export_{year}.csv"
    if target.exists():
        return True
    seed = SEED_DIR / f"export_{year}.csv.gz"
    if not seed.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(gzip.decompress(seed.read_bytes()))
    return True


async def main() -> None:
    # Default to the three most recent exports we actually have; seeds
    # ship with the repo (scimagojr.com is Cloudflare-hard to download).
    landing = Path(get_settings().landing_dir)
    years = [int(a) for a in sys.argv[1:]]
    if not years:
        have = {int(p.name[7:11]) for p in SEED_DIR.glob("export_*.csv.gz")}
        have |= {int(p.name[7:11]) for p in (landing / SOURCE).glob("export_*.csv")}
        years = sorted(have, reverse=True)[:3]
        if not years:
            print(json.dumps({"skipped": "no scimagojr exports available"}))
            return
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
