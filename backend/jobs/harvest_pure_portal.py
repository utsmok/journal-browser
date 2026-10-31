"""Harvest the Pure portal org tree (research.utwente.nl): fill missing
pure_org_parents edges from the public organisations feed and upgrade
org_type labels, with institutes pinned to the root (see
journal_browser.harvest.pure_portal for the full contract).

--dry-run fetches and reports without writing (DB reads only).

uv run python jobs/harvest_pure_portal.py [--institution ut] [--dry-run]
                                          [--max-pages 120]
"""

import asyncio
import json

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.common import resolve_institution, run_harvest
from journal_browser.harvest.pure_portal import (
    ORGANISATIONS_URL,
    apply_portal_tree,
    walk_portal_orgs,
)
from journal_browser.ingest import IngestSession


async def fetch_page(page: int) -> bytes:
    url = f"{ORGANISATIONS_URL}?format=rss"
    if page > 1:
        url += f"&page={page}"
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        response = await client.get(url, headers={"Accept": "application/rss+xml"})
        response.raise_for_status()
        return response.content


async def run(session, institution, *, dry_run: bool, max_pages: int) -> bool:
    units = await walk_portal_orgs(fetch_page, max_pages=max_pages)
    if not units:
        print("pure-portal: organisations feed returned no units; nothing to do")
        return True

    if dry_run:
        # Read-only: compute the same stats without writing or ingesting
        # payloads; apply_portal_tree's pending writes are rolled back.
        stats = await apply_portal_tree(
            session, institution, units, IngestSession(session), store_payloads=False
        )
        await session.rollback()
    else:
        stats = await run_harvest(
            "pure-portal",
            "organisations",
            f"inst:{institution.code}",
            {"portal": ORGANISATIONS_URL, "max_pages": max_pages},
            lambda ingest: apply_portal_tree(session, institution, units, ingest),
            session,
            institution_id=institution.id,
        )
    print(f"pure-portal[{institution.code}]: {json.dumps(stats)}")
    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--institution", default=None, help="institution code (default: env)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch + report stats without writing (DB reads only)",
    )
    parser.add_argument("--max-pages", type=int, default=120)
    args = parser.parse_args()

    async def main() -> None:
        engine = create_async_engine(get_settings().database_url)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            institution = await resolve_institution(session, args.institution)
            await run(session, institution, dry_run=args.dry_run, max_pages=args.max_pages)
        await engine.dispose()

    asyncio.run(main())
