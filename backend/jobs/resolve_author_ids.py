"""Resolve author identities (the ported cascade) for one institution —
or all hosted ones.

Sweeps the OpenAlex author listing (ror filter), runs the work-anchored
cascade over work_pure_authors x openalex_works, writes the
author_identities review surface, enriches works for resolved authors
(budget-capped) and re-projects the works store.

uv run python jobs/resolve_author_ids.py [--institution rug]
       [--listing-limit N] [--no-sweeps]
"""

import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.author_ids import resolve_author_ids
from journal_browser.harvest.common import get_active_institutions, resolve_institution


async def main(
    code: str | None = None, listing_limit: int | None = None, no_sweeps: bool = False
) -> None:
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        if code:
            institutions = [await resolve_institution(session, code)]
        else:
            institutions = await get_active_institutions(session)
        stats = {}
        for institution in institutions:
            stats[institution.code or str(institution.id)] = await resolve_author_ids(
                session,
                institution,
                run_sweeps=not no_sweeps,
                listing_limit=listing_limit,
            )
    await engine.dispose()
    print(json.dumps(stats))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--institution", default=None, help="institution code (default: all)")
    parser.add_argument("--listing-limit", type=int, default=None)
    parser.add_argument(
        "--no-sweeps",
        action="store_true",
        help="resolve against stored data only (no OpenAlex API calls)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.institution, args.listing_limit, args.no_sweeps))
