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
    WITH parsed AS (
        SELECT j.issn_l,
               max((e->>'year')::int)
                 FILTER (
                   WHERE e->>'works_count' ~ '^[0-9]+$'
                     AND coalesce((e->>'works_count')::int, 0) > 0
                 ) AS latest,
               sum(CASE WHEN e->>'works_count' ~ '^[0-9]+$'
                        THEN (e->>'works_count')::int ELSE 0 END)
                 FILTER (WHERE (e->>'year')::int >= :window_start
                         AND (e->>'year')::int <= :window_end) AS total
        FROM journals j, jsonb_array_elements(j.counts_by_year) e
        WHERE e->>'year' ~ '^[0-9]+$'
        GROUP BY j.issn_l
    )
    UPDATE journals
    SET last_active_year = parsed.latest,
        works_2020_plus = coalesce(parsed.total, 0)
    FROM parsed
    WHERE journals.issn_l = parsed.issn_l
      AND (
        journals.last_active_year IS DISTINCT FROM parsed.latest
        OR journals.works_2020_plus IS DISTINCT FROM coalesce(parsed.total, 0)
      )
    """
)

# Journals re-harvested with empty/NULL counts_by_year must not keep stale
# flags from an earlier harvest (the aggregate above never sees them).
RESET_EMPTY = text(
    """
    UPDATE journals
    SET last_active_year = NULL, works_2020_plus = 0
    WHERE (counts_by_year IS NULL OR counts_by_year = '[]'::jsonb)
      AND (last_active_year IS NOT NULL OR works_2020_plus IS DISTINCT FROM 0)
    """
)


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    params = {
        "window_start": settings.data_window_start,
        "window_end": settings.data_window_end or 9999,
    }
    async with engine.begin() as conn:
        result = await conn.execute(UPDATE, params)
        reset = await conn.execute(RESET_EMPTY)
    await engine.dispose()
    print(json.dumps({"rows_updated": result.rowcount, "rows_reset": reset.rowcount}))


if __name__ == "__main__":
    asyncio.run(main())
