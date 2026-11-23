"""funder_aliases derive -> funder_aliases.

Usage: uv run python jobs/derive_funder_aliases.py

Resolves every OpenAIRE funder name to the OpenAlex funder it names, from
the stored OpenAlex awards (work_funders) and OpenAIRE projects
(openaire_work_facts). Makes no API calls. Run it after
jobs/harvest_work_funders.py, whose rows it reads.
"""

import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.funder_aliases import derive_funder_aliases
from journal_browser.logging_setup import configure_logging


async def main() -> None:
    configure_logging()
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        stats = await derive_funder_aliases(session)
        await session.commit()
    await engine.dispose()
    print(json.dumps(stats))


if __name__ == "__main__":
    asyncio.run(main())
