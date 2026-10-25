"""Harvest Pure publications: ut_works canonical corpus (phases 8).

Examples:
    uv run python jobs/harvest_pure.py                      # current year set
    uv run python jobs/harvest_pure.py --full-sweep         # 2020..now + retire absent
    uv run python jobs/harvest_pure.py --years 2024-2025    # partial (never retires)
    uv run python jobs/harvest_pure.py --cerif              # CERIF enrichment pass
"""

import asyncio
import datetime as dt

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.pure import (
    harvest_pure_cerif,
    harvest_pure_years,
)


def parse_years(spec: str) -> list[int]:
    """'2020-2026' or '2023' -> year list."""
    if "-" in spec:
        lo, hi = spec.split("-", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(spec)]


async def main(session, limit: int | None, years=None, cerif=False, full_sweep=False):
    if cerif:
        stats = await harvest_pure_cerif(session, limit=limit)
    else:
        if full_sweep:
            # Retirement is only sound against a complete baseline: every
            # configured window year, not whatever subset --years named.
            years = get_settings().window_years
        elif years is None:
            years = [dt.date.today().year]
        stats = await harvest_pure_years(session, years, limit=limit, full_sweep=full_sweep)
    print(stats)
    return stats


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=parse_years, default=None)
    parser.add_argument("--cerif", action="store_true", help="CERIF enrichment pass")
    parser.add_argument(
        "--full-sweep",
        action="store_true",
        help="treat this run as a full re-baseline (retires absent works)",
    )
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    async def run() -> None:
        engine = create_async_engine(get_settings().database_url)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            await main(
                session,
                args.limit,
                years=args.years,
                cerif=args.cerif,
                full_sweep=args.full_sweep,
            )
        await engine.dispose()

    asyncio.run(run())
