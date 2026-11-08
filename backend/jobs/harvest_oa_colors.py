"""Fill journals.oa_status_observed from locally held works — no API calls.

Usage: uv run python jobs/harvest_oa_colors.py

Aggregates the stored oa_status of works linked to each journal and
stores the modal non-green color. Fills NULLs only, so it is resumable
and cheap to rerun after journal sweeps.
"""

import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.journal_oa import derive_oa_colors_local


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        stats = await derive_oa_colors_local(session)
        await session.commit()
    await engine.dispose()
    print(json.dumps(stats))


if __name__ == "__main__":
    asyncio.run(main())
