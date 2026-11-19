"""Backfill work_pure_authors from already-stored CERIF publication records.

Bootstrap step "pure-authors" (after openalex-works, before author-ids);
also manually runnable. One pass over the institution's latest stored
work_cerif_full export versions preferred over the stream's work_cerif
records (which truncate author identity), scoped per institution. Parse each record's
metadata_xml, extract the CERIF author list, and replace that work's pure
authorship edges. Covers works whose cerif record landed before its works
row (the live path skips those) and works harvested before the author
extraction existed.

uv run python jobs/backfill_pure_authors.py [--institution rug]
"""

import asyncio
import json
import logging
import time

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.common import resolve_institution
from journal_browser.harvest.pure.cerif import publication_contributors
from journal_browser.harvest.pure.entities import latest_publication_records, parse_metadata_xml
from journal_browser.harvest.pure.store import store_pure_work_authors

logger = logging.getLogger(__name__)


async def backfill_pure_work_authors(session, institution) -> dict:
    """Extract + store pure authorship edges for every stored cerif
    publication of one institution."""
    started = time.monotonic()
    # Latest stored version per Pure uuid: full-author export versions
    # preferred over the stream's truncated ones, scoped to this
    # institution's runs.
    latest = await latest_publication_records(session, institution.id)
    works = 0
    edges = 0
    parse_failures = 0
    for uuid, payload in sorted(latest.items()):
        root = parse_metadata_xml(payload.get("metadata_xml"))
        if root is None:
            parse_failures += 1
            continue
        authors = publication_contributors(root, "Author")
        if not authors:
            continue
        works += 1
        edges += await store_pure_work_authors(
            session,
            uuid,
            authors,
            institution_id=institution.id,
        )
    stats = {
        "cerif_records": len(latest),
        "works_with_authors": works,
        "edges": edges,
        "parse_failures": parse_failures,
        "seconds": round(time.monotonic() - started, 1),
    }
    logger.info("backfill pure work authors[%s]: %s", institution.code, stats)
    return stats


async def main(code: str | None = None) -> None:
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        institution = await resolve_institution(session, code)
        stats = await backfill_pure_work_authors(session, institution)
        await session.commit()
    await engine.dispose()
    print(json.dumps(stats))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--institution", default=None, help="institution code (default: env)")
    args = parser.parse_args()
    asyncio.run(main(args.institution))
