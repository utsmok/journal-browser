"""Recompute derived journal flags from stored counts_by_year.

Idempotent full recompute: last_active_year and works_2020_plus are
rebuildable at any time. in_scimago is owned by the scimagojr ingest
(it backfills on every run).

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
        works_2020_plus = coalesce(y.total, 0)
    FROM (
        SELECT issn_l,
               max((e->>'year')::int)
                 FILTER (WHERE coalesce((e->>'works_count')::int, 0) > 0) AS latest,
               sum((e->>'works_count')::int) FILTER (WHERE (e->>'year')::int >= 2020) AS total
        FROM journals, jsonb_array_elements(counts_by_year) e
        GROUP BY issn_l
    ) y
    WHERE journals.issn_l = y.issn_l
      AND (
        journals.last_active_year IS DISTINCT FROM y.latest
        OR journals.works_2020_plus IS DISTINCT FROM coalesce(y.total, 0)
      )
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
