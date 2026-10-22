"""Backfill quality-bar flags for rows harvested before decision 12.

Idempotent: recomputes last_active_year/is_active_recently from the
already-stored counts_by_year. in_scimago is owned by the scimagojr
ingest (it backfills on every run).

Usage: uv run python jobs/backfill_flags.py
"""

import asyncio
import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from journal_browser.config import get_settings

UPDATE = text(
    """
    UPDATE journals
    SET last_active_year = y.latest,
        is_active_recently = coalesce(y.latest >= 2020, false)
    FROM (
        SELECT issn_l, max((e->>'year')::int) AS latest
        FROM journals, jsonb_array_elements(counts_by_year) e
        WHERE coalesce((e->>'works')::int, 0) > 0
        GROUP BY issn_l
    ) y
    WHERE journals.issn_l = y.issn_l
      AND journals.last_active_year IS DISTINCT FROM y.latest
    """
)


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        result = await conn.execute(UPDATE)
    await engine.dispose()
    print(json.dumps({"rows_updated": result.rowcount}))


if __name__ == "__main__":
    asyncio.run(main())
