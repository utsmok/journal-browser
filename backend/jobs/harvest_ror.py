"""ROR records -> partner_institutions.

Usage: uv run python jobs/harvest_ror.py [--dump PATH] [--refresh] [--ttl-days 30] [--limit N]

Fetches the ROR record of every partner the table only knows from a work
payload, and again of every stored record older than --ttl-days (default
30). --refresh re-fetches every stored partner; --limit N stops after N
rows.

--dump PATH first loads every partner's record from a ROR data dump (the
zip from https://zenodo.org/communities/ror-data, or its JSON file), with
no API calls. The API pass then asks only about the partners the dump
lacks. Use it for a first fill or after a long gap.
"""

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.ror import TTL_DAYS, harvest_ror, load_ror_dump
from journal_browser.logging_setup import configure_logging


async def run(dump: Path | None, refresh: bool, ttl_days: int, limit: int | None) -> None:
    configure_logging()
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        if dump is not None:
            print(json.dumps({"dump": await load_ror_dump(session, dump)}))
        stats = await harvest_ror(session, refresh=refresh, limit=limit, ttl_days=ttl_days)
        await session.commit()
    await engine.dispose()
    print(json.dumps(stats))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump", type=Path, help="load records from this ROR data dump first")
    parser.add_argument("--refresh", action="store_true", help="re-fetch every stored record")
    parser.add_argument(
        "--ttl-days",
        type=int,
        default=TTL_DAYS,
        help="fetch a stored record again when it is older than this many days",
    )
    parser.add_argument("--limit", type=int, help="stop after this many records")
    opts = parser.parse_args()
    asyncio.run(run(opts.dump, opts.refresh, max(opts.ttl_days, 0), opts.limit))
