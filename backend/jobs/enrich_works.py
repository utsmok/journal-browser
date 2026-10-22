"""Enrich ut_works: OpenAlex -> Crossref -> CERIF journal ladder + summary.

    uv run python jobs/enrich_works.py            # full ladder run
    uv run python jobs/enrich_works.py --limit 100
    uv run python jobs/enrich_works.py --summary  # just print acceptance metrics
"""

import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.enrich import (
    enrich_crossref,
    enrich_openalex,
    enrichment_summary,
    resolve_journals_cerif,
)


async def main(session, limit: int | None, summary_only: bool) -> None:
    if summary_only:
        print(json.dumps(await enrichment_summary(session), indent=1))
        return
    stats = {"openalex": await enrich_openalex(session, limit)}
    await session.commit()
    stats["crossref"] = await enrich_crossref(session, limit)
    await session.commit()
    stats["cerif"] = await resolve_journals_cerif(session, limit)
    stats["summary"] = await enrichment_summary(session)
    print(json.dumps(stats, indent=1, default=str))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    async def run() -> None:
        engine = create_async_engine(get_settings().database_url)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            await main(session, args.limit, args.summary)
        await engine.dispose()

    asyncio.run(run())
