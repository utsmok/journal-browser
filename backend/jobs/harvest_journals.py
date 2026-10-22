"""Full OpenAlex sources sweep + quality-bar counts (decisions.md #12).

Usage: uv run python jobs/harvest_journals.py [--seed-deals-only]
"""

import asyncio
import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.openalex_journals import (
    harvest_journals,
    refresh_publisher_links,
    seed_deal_journals,
)
from journal_browser.models import Journal
from journal_browser.services.search import quality_bar_clause


async def quality_counts(session) -> dict[str, int]:
    in_bar = await session.scalar(
        select(func.count()).select_from(Journal).where(quality_bar_clause())
    )
    total = await session.scalar(select(func.count()).select_from(Journal))
    return {"quality_bar": int(in_bar or 0), "all": int(total or 0)}


async def main() -> None:
    import sys

    seed_only = "--seed-deals-only" in sys.argv
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        seeded = await seed_deal_journals(None, session) if seed_only else {}
        stats = {} if seed_only else await harvest_journals(session)
        linked = await refresh_publisher_links(session)
        counts = await quality_counts(session)
        await session.commit()
    await engine.dispose()
    print(
        json.dumps(
            {"seed_deals": seeded, "sweep": stats, "publishers_linked": linked, "corpus": counts}
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
