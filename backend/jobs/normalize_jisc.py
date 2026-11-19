"""Normalize all landed JISC Open Policy Finder records into canon tables.

Usage: uv run python jobs/normalize_jisc.py

Reads the latest source_records payload per (entity_type, source_pk),
upserts the six jisc_* tables and stamps journals.jisc_* by ISSN match.
Run after jobs/harvest_jisc.py; rerun freely (idempotent full refresh).
"""

import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.jisc_normalize import normalize_jisc


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        stats = await normalize_jisc(session)
        await session.commit()
    await engine.dispose()
    print(json.dumps(stats))


if __name__ == "__main__":
    asyncio.run(main())
