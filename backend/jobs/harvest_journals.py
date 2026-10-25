"""Full OpenAlex sources sweep + corpus-cutoff counts (decisions.md #15).

Usage: uv run python jobs/harvest_journals.py [--seed-deals-only]
"""

import asyncio
import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.openalex_journals import harvest_journals, refresh_publisher_links
from journal_browser.models import Journal
from journal_browser.services.search import WORKS_CUTOFF


async def corpus_counts(session) -> dict[str, int]:
    in_cut = await session.scalar(select(func.count()).select_from(Journal).where(WORKS_CUTOFF))
    total = await session.scalar(select(func.count()).select_from(Journal))
    return {"cutoff": int(in_cut or 0), "all": int(total or 0)}


async def main() -> None:
    import sys

    seed_only = "--seed-deals-only" in sys.argv
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        stats = await harvest_journals(session, seed_only=seed_only)
        linked = await refresh_publisher_links(session)
        counts = await corpus_counts(session)
        await session.commit()
    await engine.dispose()
    print(json.dumps({"sweep": stats, "publishers_linked": linked, "corpus": counts}))


if __name__ == "__main__":
    asyncio.run(main())
