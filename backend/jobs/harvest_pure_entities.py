"""Harvest Pure CERIF entity sets (orgunits + persons) for one institution.

The standalone author canon: pure_orgs/pure_org_parents (org tree for the
affiliation closure) and pure_persons (roster with ORCIDs and profile
affiliations). Records land verbatim in source_records first; the
normalized copies rebuild from the latest stored version per record, so
re-runs are idempotent and XML changes flow through.

uv run python jobs/harvest_pure_entities.py [--institution rug] [--limit N]
"""

import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.common import resolve_institution
from journal_browser.harvest.pure import harvest_pure_entities


async def main(code: str | None = None, limit: int | None = None) -> None:
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        institution = await resolve_institution(session, code)
        stats = await harvest_pure_entities(session, institution, limit=limit)
    await engine.dispose()
    print(json.dumps(stats))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--institution", default=None, help="institution code (default: env)")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    asyncio.run(main(args.institution, args.limit))
