"""Sweep all JISC Open Policy Finder item types into landing (raw JSON).

Usage: uv run python jobs/harvest_jisc.py [--only publication] [--limit-records 3]

Each item type (publication, publisher, publisher_policy, funder,
funder_group, repository) gets its own HarvestRun and lands verbatim in
source_records; normalization onto the jisc_* tables is
jobs/normalize_jisc.py. Idempotent full refresh: reruns dedupe on
content_hash.
"""

import argparse
import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.jisc_opf import SWEEP_TYPES, harvest_all


async def main(only: str | None, limit_records: int | None, sleep_s: float) -> None:
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        stats = await harvest_all(session, only=only, limit_records=limit_records, sleep_s=sleep_s)
    await engine.dispose()
    print(json.dumps(stats))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only", choices=SWEEP_TYPES, default=None, help="sweep one item type only"
    )
    parser.add_argument(
        "--limit-records",
        type=int,
        default=None,
        help="cap new records across the sweep (smoke runs)",
    )
    parser.add_argument("--sleep", type=float, default=0.15, help="seconds between pages")
    args = parser.parse_args()
    asyncio.run(main(args.only, args.limit_records, args.sleep))
