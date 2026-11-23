"""work_partners derive -> work_partners + partner_institutions stubs.

Usage: uv run python jobs/derive_work_partners.py

Rebuilds every hosted institution's partner links from the stored OpenAlex
and OpenAIRE work payloads. Makes no API calls. Run jobs/harvest_ror.py
afterwards for the ROR records of new partners.
"""

import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.work_partners import derive_work_partners


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        stats = await derive_work_partners(session)
        await session.commit()
    await engine.dispose()
    print(json.dumps(stats))


if __name__ == "__main__":
    asyncio.run(main())
