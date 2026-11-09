"""people.utwente.nl profile sweep -> people_utwente_persons / _orgs.

Usage: uv run python jobs/harvest_people_utwente.py [--institution ut]
    [--limit N] [--retry-missed] [--refresh] [--dry-run]

Paces ~0.5 s per author (search + up to 5 profile fetches + optional
portrait); a full first run over the confirmed roster takes hours — run
it in chunks with --limit. Per-author outcomes are stamped, so re-runs
only see new authors (--retry-missed / --refresh re-open old ones).
"""

import argparse
import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.common import resolve_institution, run_harvest
from journal_browser.harvest.people_utwente import harvest_people_utwente
from journal_browser.ingest import IngestSession


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--institution", default=None, help="institution code (default: env home)")
    parser.add_argument("--limit", type=int, default=None, help="max authors to attempt this run")
    parser.add_argument("--retry-missed", action="store_true", help="re-attempt missed authors")
    parser.add_argument("--refresh", action="store_true", help="re-attempt all attempted authors")
    parser.add_argument("--dry-run", action="store_true", help="match and report, write nothing")
    args = parser.parse_args()

    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        institution = await resolve_institution(session, args.institution)
        code = institution.code
        config = {
            "limit": args.limit,
            "retry_missed": args.retry_missed,
            "refresh": args.refresh,
        }
        if args.dry_run:
            stats = await harvest_people_utwente(
                session,
                institution,
                ingest=IngestSession(session),
                limit=args.limit,
                retry_missed=args.retry_missed,
                refresh=args.refresh,
                dry_run=True,
            )
            await session.rollback()
        else:
            stats = await run_harvest(
                "people-utwente",
                "persons",
                f"inst:{code}",
                config,
                lambda ingest: harvest_people_utwente(
                    session,
                    institution,
                    ingest=ingest,
                    limit=args.limit,
                    retry_missed=args.retry_missed,
                    refresh=args.refresh,
                ),
                session,
                institution_id=institution.id,
            )
    await engine.dispose()
    print(json.dumps(stats))


if __name__ == "__main__":
    asyncio.run(main())
