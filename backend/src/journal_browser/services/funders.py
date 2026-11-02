"""Funder list/detail support: UT-work attribution from work_funders.

The work_funders table (migration 0049) may not exist yet; every read
checks to_regclass first and degrades to zeros ("harvest pending") instead
of 500ing. Raw SQL on purpose: no ORM model until the migration lands."""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def _work_funders_ready(session: AsyncSession) -> bool:
    return bool(await session.scalar(text("select to_regclass('public.work_funders') is not null")))


async def ut_work_counts(session: AsyncSession, institution_id: int) -> dict[str, int]:
    """UT works per funder_openalex_id for this institution."""
    if not await _work_funders_ready(session):
        return {}
    rows = await session.execute(
        text(
            "select funder_openalex_id, count(distinct pure_uuid) as n"
            " from work_funders where institution_id = :i group by 1"
        ),
        {"i": institution_id},
    )
    return {r[0]: int(r[1]) for r in rows}


async def top_journals(
    session: AsyncSession, institution_id: int, openalex_funder_id: str | None, limit: int = 5
) -> list[dict[str, Any]]:
    """Journals with the most works crediting this funder."""
    if not await _work_funders_ready(session) or openalex_funder_id is None:
        return []
    rows = await session.execute(
        text(
            "select j.title, j.issn_l, count(distinct wf.pure_uuid) as n"
            " from work_funders wf"
            " join works w on w.institution_id = wf.institution_id and w.pure_uuid = wf.pure_uuid"
            " join journals j on j.issn_l = w.journal_issn_l"
            " where wf.institution_id = :i and wf.funder_openalex_id = :f"
            " group by j.title, j.issn_l order by n desc limit :l"
        ),
        {"i": institution_id, "f": openalex_funder_id, "l": limit},
    )
    return [{"title": r[0], "issn_l": r[1], "n_works": int(r[2])} for r in rows]
