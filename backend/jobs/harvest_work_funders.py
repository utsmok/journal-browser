"""Per-work OpenAlex funder/grant harvest -> work_funders.

Usage: uv run python jobs/harvest_work_funders.py [--ttl-days 30]

Only re-fetches works whose funders state is older than the TTL (default
30, override with --ttl-days or JB_WORK_FUNDERS_TTL_DAYS); works fetched
more recently are skipped.
"""

import asyncio
import json
import os

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.work_funders import harvest_work_funders
from journal_browser.logging_setup import configure_logging


def _ttl_days(argv: list[str] | None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ttl-days",
        type=int,
        # compose passes an unset variable through as "", which is the default.
        default=int(os.environ.get("JB_WORK_FUNDERS_TTL_DAYS") or 30),
        help="re-fetch a work when its last funders fetch is older than this",
    )
    args, _ = parser.parse_known_args(argv)
    return max(args.ttl_days, 0)


async def main() -> None:
    configure_logging()
    ttl_days = _ttl_days(None)
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        stats = await harvest_work_funders(session, ttl_days=ttl_days)
        await session.commit()
    await engine.dispose()
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
