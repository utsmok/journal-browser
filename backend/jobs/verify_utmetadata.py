"""Dev-only cross-check against the ut-metadata database (phase 10 gate).

Compares journal-browser's canonical corpus and pure_canon stats against
ut-metadata's verbatim Pure harvest:

- ut_works 2020+ total vs ut-metadata year-set records (2% tolerance),
- per-year counts,
- top-20 journal 2023 counts (pure_canon vs ut-metadata equivalent).

Requires network access to the ut-metadata DB; gated by
JB_UTMETADATA_DSN (dev machines set it in backend/.env, never tracked).

Usage: uv run python jobs/verify_utmetadata.py
"""

import asyncio
import json
import os
import sys

import asyncpg
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.models import InstitutionWorksStats

DEFAULT_DSN = "postgresql://ut_metadata:ut_metadata@localhost:5434/ut_metadata"
TOP_JOURNAL_YEAR = 2023


async def ours(session) -> dict:
    from sqlalchemy import func, select

    from journal_browser.models import UtWork

    per_year = dict(
        (await session.execute(
            select(UtWork.year, func.count()).group_by(UtWork.year)
        )).all()
    )
    return {"total": sum(per_year.values()), "per_year": per_year}


async def theirs(conn) -> dict:
    rows = await conn.fetch("""
        SELECT regexp_replace(s, 'publications:year', '') AS y, count(DISTINCT source_pk)
        FROM (
            SELECT source_pk, jsonb_array_elements_text(payload->'set_specs') AS s
            FROM source_records WHERE source='pure' AND entity_type='works'
        ) z
        WHERE s ~ '^publications:year20(2[0-9])$'
        GROUP BY y ORDER BY y
    """)
    per_year = {int(r["y"]): r["count"] for r in rows}
    return {"total": sum(per_year.values()), "per_year": per_year}


async def top_journals(session, conn) -> list[dict]:
    from sqlalchemy import select

    from journal_browser.models import Journal

    ours_rows = (
        await session.execute(
            select(InstitutionWorksStats.issn_l, InstitutionWorksStats.works_count, Journal.title)
            .join(Journal, Journal.issn_l == InstitutionWorksStats.issn_l)
            .where(
                InstitutionWorksStats.source == "pure_canon",
                InstitutionWorksStats.year == TOP_JOURNAL_YEAR,
            )
            .order_by(InstitutionWorksStats.works_count.desc())
            .limit(20)
        )
    ).all()
    # ut-metadata has no per-journal/year cut in a documented table (its
    # work_venues link uses OpenAlex S-ids, not venue ids), so the top-20 is
    # reported for eyeballing only; the 2% corpus gate is the real check.
    return [
        {"issn_l": issn_l, "title": (title or "")[:40], "ours": count}
        for issn_l, count, title in ours_rows
    ]


async def main() -> None:
    dsn = os.environ.get("JB_UTMETADATA_DSN") or DEFAULT_DSN
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        ours_stats = await ours(session)
        conn = await asyncpg.connect(dsn, timeout=10)
        try:
            their_stats = await theirs(conn)
            tolerance = 0.02 if their_stats["total"] else 1.0
            delta = abs(ours_stats["total"] - their_stats["total"]) / max(
                1, their_stats["total"]
            )
            report = {
                "ours_2020plus": ours_stats,
                "utmeta_2020plus": their_stats,
                "total_delta_pct": round(delta * 100, 2),
                "within_2pct": delta <= tolerance,
                f"top20_{TOP_JOURNAL_YEAR}": await top_journals(session, conn),
            }
        finally:
            await conn.close()
    await engine.dispose()
    print(json.dumps(report, indent=1, default=str))
    if not report.get("within_2pct"):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
