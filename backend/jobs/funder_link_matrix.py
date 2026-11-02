"""JISC <-> OpenAlex/OpenAIRE funder link matrix (report only).

Usage: uv run python jobs/funder_link_matrix.py
"""

import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.funders import funder_link_matrix


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        matrix = await funder_link_matrix(session)
    await engine.dispose()
    print(json.dumps(matrix, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
