"""Dev-only cross-check against the ut-metadata database (phase 10 gate).

Compares journal-browser's canonical corpus and pure_canon stats against
ut-metadata's verbatim Pure harvest:

- works 2020+ total vs ut-metadata year-set records (2% tolerance),
- per-year counts,
- top-20 journal 2023 counts (pure_canon vs ut-metadata equivalent).

Requires network access to the ut-metadata DB; gated by
JB_UT_METADATA_DSN (dev machines set it in backend/.env, never tracked).

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

TOP_JOURNAL_YEAR = 2023


async def ours(session, institution_id: int) -> dict:
    from sqlalchemy import func, select

    from journal_browser.models import Work

    # Same corpus the docstring promises and theirs() counts: active works,
    # 2020+ window. Unfiltered counts made every verdict permanently red.
    per_year = dict(
        (
            await session.execute(
                select(Work.year, func.count())
                .where(
                    Work.institution_id == institution_id,
                    Work.retired_at.is_(None),
                    Work.year >= 2020,
                )
                .group_by(Work.year)
            )
        ).all()
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
    # Work-distinct total: a work belonging to several year sets must count
    # once, not once per set.
    total = await conn.fetchval("""
        SELECT count(DISTINCT source_pk) FROM (
            SELECT source_pk, jsonb_array_elements_text(payload->'set_specs') AS s
            FROM source_records WHERE source='pure' AND entity_type='works'
        ) z
        WHERE s ~ '^publications:year20(2[0-9])$'
    """)
    return {"total": int(total or 0), "per_year": per_year}


async def top_journals(session, conn) -> list[dict]:
    """Top-20 per-journal 2023: ours vs ut-metadata's canonical cut, with cause.

    ut-metadata counts canonical works whose OpenAlex venue links to the
    ISSN (work_venues -> core_venue_link.openalex_issn_l); its canonical
    corpus includes affiliation-inferred works that Pure never registered,
    so their counts are supersets. A diff is "explained" when theirs >= ours
    (extra affiliated works) or the gap is small venue-linking noise.
    """
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
    theirs_map = {
        r["issn_l"]: r["n"]
        for r in await conn.fetch(
            """
            SELECT cvl.openalex_issn_l AS issn_l, count(DISTINCT mw.canonical_id) AS n
            FROM merged_work_attrs mw
            JOIN work_venues wv ON wv.work_id = mw.canonical_id
            JOIN core_venue_link cvl ON lower(cvl.openalex_source_id) = wv.source_s_id
            WHERE mw.publication_year = $1 AND cvl.openalex_issn_l IS NOT NULL
            GROUP BY 1
            """,
            TOP_JOURNAL_YEAR,
        )
    }
    out = []
    unexplained = 0
    for issn_l, count, title in ours_rows:
        n = theirs_map.get(issn_l, 0)
        if n < count and count - n > 2:
            cause = "REVIEW: ours exceeds ut-metadata canonical venue cut"
            unexplained += 1
        elif n > count:
            cause = "ut-metadata includes affiliation-inferred non-Pure works"
        else:
            cause = "match/venue-link noise"
        out.append(
            {
                "issn_l": issn_l,
                "title": (title or "")[:40],
                "ours": count,
                "utmeta": n,
                "cause": cause,
            }
        )
    out.append({"unexplained_rows": unexplained, "gate_max": 5})
    return out


async def main() -> None:
    dsn = os.environ.get("JB_UT_METADATA_DSN")
    if not dsn:
        sys.exit("set JB_UT_METADATA_DSN (see .env.example) before running")
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        from journal_browser.harvest.common import ensure_home_institution

        inst = await ensure_home_institution(session)
        ours_stats = await ours(session, inst.id)
        conn = await asyncpg.connect(dsn, timeout=10)
        try:
            their_stats = await theirs(conn)
            tolerance = 0.02 if their_stats["total"] else 1.0
            delta = abs(ours_stats["total"] - their_stats["total"]) / max(1, their_stats["total"])
            top = await top_journals(session, conn)
            report = {
                "ours_2020plus": ours_stats,
                "utmeta_2020plus": their_stats,
                "total_delta_pct": round(delta * 100, 2),
                "within_2pct": delta <= tolerance,
                f"top20_{TOP_JOURNAL_YEAR}": top,
            }
            summary = top[-1]
            report["top20_unexplained"] = summary.get("unexplained_rows", 0)
            report["green"] = (
                report["within_2pct"] and report["top20_unexplained"] <= summary["gate_max"]
            )
        finally:
            await conn.close()
    await engine.dispose()
    print(json.dumps(report, indent=1, default=str))
    if not report.get("green"):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
