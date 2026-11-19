"""people.utwente.nl profile sweep -> people_utwente_persons / _orgs.

Usage: uv run python jobs/harvest_people_utwente.py [--institution ut]
    [--limit N] [--retry-missed] [--refresh] [--concurrency N] [--dry-run]

Runs `--concurrency` (default 20, matching ea-cli's proven rate against
the same endpoint) author pipelines in flight; the confirmed roster
completes in roughly 30-45 minutes. Per-author outcomes are stamped in
batches of 50, so re-runs only see new authors (--retry-missed /
--refresh re-open old ones) and a crash loses at most the last batch.
"""

import argparse
import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.common import resolve_institution, run_harvest
from journal_browser.harvest.people_utwente import CONCURRENCY, harvest_people_utwente
from journal_browser.ingest import IngestSession


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--institution", default=None, help="institution code (default: env home)")
    parser.add_argument("--limit", type=int, default=None, help="max authors to attempt this run")
    parser.add_argument("--retry-missed", action="store_true", help="re-attempt missed authors")
    parser.add_argument("--refresh", action="store_true", help="re-attempt all attempted authors")
    parser.add_argument(
        "--confirmed-only",
        action="store_true",
        help="skip unconfirmed roster authors (mostly external co-authors)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=CONCURRENCY,
        help="author pipelines kept in flight (default: %(default)s)",
    )
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
            "confirmed_only": args.confirmed_only,
            "concurrency": args.concurrency,
        }
        if args.dry_run:
            stats = await harvest_people_utwente(
                session,
                institution,
                ingest=IngestSession(session),
                limit=args.limit,
                retry_missed=args.retry_missed,
                refresh=args.refresh,
                confirmed_only=args.confirmed_only,
                concurrency=args.concurrency,
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
                    confirmed_only=args.confirmed_only,
                    concurrency=args.concurrency,
                ),
                session,
                institution_id=institution.id,
            )
    await engine.dispose()
    print(json.dumps(stats))


if __name__ == "__main__":
    asyncio.run(main())
