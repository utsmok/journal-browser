"""Prune superseded payload versions from source_records.

  uv run python jobs/prune_source_records.py                       # dry run: report only
  uv run python jobs/prune_source_records.py --apply               # delete
  uv run python jobs/prune_source_records.py --apply --source jct  # one source at a time
  uv run python jobs/prune_source_records.py --apply --keep 2      # keep the two newest
  uv run python jobs/prune_source_records.py --apply --min-age-days 7

source_records is append-only: a changed payload lands as a new version
and the old one stayed, which grew the live table to 28.5 GB by 2026-11,
with 39% of its rows superseded. Readers need only the newest versions per
key and institution (journal_browser.retention lists them), so this job
deletes the rest. A version that apc_evidence points at is never deleted.

The default is a dry run that prints what --apply would delete: rows and
stored payload bytes per source and entity type. --apply commits one id
range at a time (10,000 ids by default). An interrupted run leaves a
consistent table, and the next run deletes what is left.

Deleted rows free space inside the table files. Run
`VACUUM (ANALYZE) source_records;` afterwards so new versions reuse it.
The files only shrink for the OS with VACUUM FULL, which takes an ACCESS
EXCLUSIVE lock; DEPLOYMENT.md ("source_records retention") has the steps.
"""

import argparse
import asyncio
import json
import logging
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.logging_setup import configure_logging
from journal_browser.retention import BATCH_IDS, prune_superseded

logger = logging.getLogger("journal_browser.jobs.prune_source_records")


async def main(apply: bool, keep: int, min_age_days: float, batch: int, source: str | None) -> None:
    configure_logging()
    engine = create_async_engine(get_settings().database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    older_than = datetime.now(UTC) - timedelta(days=min_age_days) if min_age_days else None
    started = time.monotonic()

    async def on_batch(last_id: int, selected: int, deleted: int) -> None:
        logger.info("scanned to id %d: %d selected, %d deleted", last_id, selected, deleted)

    async with session_factory() as session:
        stats = await prune_superseded(
            session,
            apply=apply,
            keep=keep,
            older_than=older_than,
            source=source,
            batch=batch,
            on_batch=on_batch,
        )
    await engine.dispose()
    stats["seconds"] = round(time.monotonic() - started, 1)
    logger.info(
        "%s finished: %d rows, %d payload bytes in %s s",
        stats["mode"],
        stats["rows"],
        stats["payload_bytes"],
        stats["seconds"],
    )
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--apply", action="store_true", help="delete the superseded versions (default: report only)"
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=1,
        help="newest versions to keep per key and institution (default: 1)",
    )
    parser.add_argument(
        "--min-age-days",
        type=float,
        default=0.0,
        help="also keep superseded versions harvested this recently (default: 0)",
    )
    parser.add_argument(
        "--source", default=None, help="restrict the scan to one source (e.g. openalex)"
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=BATCH_IDS,
        help="ids scanned and deleted per committed step (default: 10000)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.apply, args.keep, args.min_age_days, args.batch, args.source))
