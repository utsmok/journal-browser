"""Harvest the Pure portal org tree (research.utwente.nl): fill missing
pure_org_parents edges from the public organisations feed and upgrade
org_type labels, with institutes pinned to the root (see
journal_browser.harvest.pure_portal for the full contract).

--dry-run fetches and reports without writing (DB reads only).
--curated-parent "Org Name=Parent Name" (repeatable) asserts owner-approved
edges for units the portal itself lists parentless (the legacy standalone
units: Stochastic Operations Research, Discrete Mathematics and
Mathematical Programming). They run through the same gap-fill-only,
institute-pin, cycle-guard contract and are provenance-marked
(curated=true) in source_records. --skip-portal runs curated edges alone.

uv run python jobs/harvest_pure_portal.py [--institution ut] [--dry-run]
    [--max-pages 120] [--curated-parent "SOR=Faculty of EEMCS" ...]
    [--skip-portal]
"""

import asyncio
import json

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.common import resolve_institution, run_harvest
from journal_browser.harvest.pure_portal import (
    ORGANISATIONS_URL,
    PortalUnit,
    apply_portal_tree,
    curated_unit,
    walk_portal_orgs,
)
from journal_browser.ingest import IngestSession


async def fetch_page(page: int) -> bytes:
    url = f"{ORGANISATIONS_URL}?format=rss"
    if page > 1:
        url += f"&page={page}"
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        # Browser UA: the portal WAF rejects scripted default agents.
        response = await client.get(
            url,
            headers={
                "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0"
                ),
            },
        )
        response.raise_for_status()
        return response.content


def parse_curated_pairs(pairs: list[str] | None) -> list[PortalUnit]:
    units: list[PortalUnit] = []
    for raw in pairs or []:
        org, sep, parent = raw.partition("=")
        if not sep or not org.strip() or not parent.strip():
            raise SystemExit(f"invalid --curated-parent {raw!r}: 'Org Name=Parent Name' expected")
        units.append(curated_unit(org.strip(), parent.strip()))
    return units


async def run(
    session,
    institution,
    *,
    dry_run: bool,
    max_pages: int,
    curated: list[PortalUnit],
    skip_portal: bool,
) -> bool:
    units = curated
    if not skip_portal:
        portal_units = await walk_portal_orgs(fetch_page, max_pages=max_pages)
        if not portal_units and not curated:
            print("pure-portal: organisations feed returned no units; nothing to do")
            return True
        units = portal_units + curated

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
            {"portal": ORGANISATIONS_URL, "max_pages": max_pages, "curated": len(curated)},
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
    parser.add_argument(
        "--curated-parent",
        action="append",
        default=[],
        metavar="ORG=PARENT",
        help="owner-approved parent edge for a portal-parentless org (repeatable)",
    )
    parser.add_argument(
        "--skip-portal",
        action="store_true",
        help="run curated edges only (no feed fetch)",
    )
    args = parser.parse_args()

    async def main() -> None:
        engine = create_async_engine(get_settings().database_url)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            institution = await resolve_institution(session, args.institution)
            await run(
                session,
                institution,
                dry_run=args.dry_run,
                max_pages=args.max_pages,
                curated=parse_curated_pairs(args.curated_parent),
                skip_portal=args.skip_portal,
            )
        await engine.dispose()

    asyncio.run(main())
