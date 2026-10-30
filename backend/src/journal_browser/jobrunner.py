"""Shared CLI runner for ingestion jobs.

Usage inside a job module::

    from journal_browser.jobrunner import run_job

    async def main(session, limit):
        ...

    if __name__ == "__main__":
        run_job(main)
"""

import argparse
import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings


def run_job(async_main) -> None:
    """Parse --limit, open one session, run async_main(session, limit)."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="cap records processed")
    args = parser.parse_args()

    async def run() -> None:
        engine = create_async_engine(get_settings().database_url)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            await async_main(session, args.limit)
        await engine.dispose()

    asyncio.run(run())
