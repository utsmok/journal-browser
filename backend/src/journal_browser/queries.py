"""Shared session and SQL query helpers used by harvest and services alike.

This module imports neither package, so either side can depend on it
without a cycle.
"""

from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from .config import EXCLUDED_WORK_TYPES
from .models import CacheEpoch, Institution


async def cache_epoch(session: AsyncSession) -> Any:
    """Current harvest epoch; in-process caches key on this so a harvest in
    another process invalidates them on the next request."""
    return await session.scalar(select(CacheEpoch.bumped_at).where(CacheEpoch.id == 1))


def oa_openness_rank(column: Any):
    """Ascending openness rank for an oa_status column (owner decision
    2026-11-05, canonical merge across duplicate OpenAlex records):
    diamond > gold > hybrid > bronze > green > closed."""
    return case(
        (column == "diamond", 5),
        (column == "gold", 4),
        (column == "hybrid", 3),
        (column == "bronze", 2),
        (column == "green", 1),
        (column == "closed", 0),
        else_=-1,
    )


def oa_openness_desc(column: Any):
    """Sort expression: most open oa_status first."""
    return oa_openness_rank(column).desc()


async def get_active_institutions(session: AsyncSession) -> list[Institution]:
    """Hosted institutions (code + active), by id (the home institution
    keeps the first slot)."""
    rows = await session.execute(
        select(Institution)
        .where(Institution.active.is_(True), Institution.code.is_not(None))
        .order_by(Institution.id)
    )
    return list(rows.scalars().all())


def work_type_normalized(column: Any) -> ColumnElement:
    """The normalized work type (lower-cased, info:eu-repo/semantics/
    stripped, hyphens collapsed) so SQL filters match Python's
    config.normalize_work_type exactly."""
    return func.lower(
        func.replace(
            func.replace(func.coalesce(column, ""), "info:eu-repo/semantics/", ""), "-", ""
        )
    )


def work_type_not_excluded(column: Any) -> ColumnElement:
    """SQL twin of config.work_type_excluded: the normalized work type
    is not one of the never-journal-output types. One definition for every
    query that must describe the same population as the pure_canon stats
    (write_pure_canon_stats was the first consumer)."""
    return work_type_normalized(column).not_in(sorted(EXCLUDED_WORK_TYPES))
