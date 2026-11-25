"""Remove the dropped payload keys from stored source_records payloads.

  uv run python jobs/strip_source_records.py            # dry run: report only
  uv run python jobs/strip_source_records.py --apply    # rewrite the payloads

The ingest projection (ingest.PAYLOAD_DROP_KEYS) stops storing keys that no
reader uses. Rows written before it existed still carry them, and this job
removes those keys in place. id, content_hash and harvested_at stay as they
were. The default is a dry run that reports the rows and compressed payload
bytes --apply would rewrite.

Run jobs/prune_source_records.py first: superseded versions are deleted,
not rewritten. Each rewritten payload lands as a new row version, so the
table needs space for the new copies until `VACUUM (ANALYZE) source_records;`
reclaims the old ones. DEPLOYMENT.md ("source_records retention") has the
steps.
"""

import argparse
import asyncio
import json
import logging
import time

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.logging_setup import configure_logging
from journal_browser.retention import BATCH_IDS, strip_stored_payloads

logger = logging.getLogger("journal_browser.jobs.strip_source_records")


async def main(apply: bool, batch: int) -> None:
    configure_logging()
    engine = create_async_engine(get_settings().database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    started = time.monotonic()

    async def on_batch(group: str, last_id: int, rows: int, before: int, after: int) -> None:
        if rows:
            logger.info(
                "%s up to id %d: %d payloads, %d -> %d bytes",
                group,
                last_id,
                rows,
                before,
                after,
            )

    async with session_factory() as session:
        stats = await strip_stored_payloads(session, apply=apply, batch=batch, on_batch=on_batch)
    await engine.dispose()
    stats["seconds"] = round(time.monotonic() - started, 1)
    logger.info(
        "%s finished: %d payloads, %d -> %d bytes in %s s",
        stats["mode"],
        stats["rows"],
        stats["payload_bytes_before"],
        stats["payload_bytes_after"],
        stats["seconds"],
    )
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--apply", action="store_true", help="rewrite the payloads (default: report only)"
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=BATCH_IDS,
        help="ids scanned and rewritten per committed step (default: 10000)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.apply, args.batch))
