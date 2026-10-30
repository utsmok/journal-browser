"""Shared author-works query fragments: joins, window bounds, strata, and
the OA year buckets. New queries touching author works import these; inline
copies get rejected in review."""

from typing import Any

from sqlalchemy import and_, false, or_
from sqlalchemy.sql.elements import ColumnElement

from ..models import Author, AuthorWork, Work

WORKS_STRATA = ("1-4", "5-19", "20-49", "50+")
_STRATA_BOUNDS = {"1-4": (1, 4), "5-19": (5, 19), "20-49": (20, 49)}  # 50+ = >= 50

#: Response buckets of works.oa_status (year splits carry all six).
YEAR_BUCKETS = ("gold", "green", "hybrid", "bronze", "closed", "diamond")

# 9999 as a SQL bound is byte-identical in effect to unbounded for year
# columns; an open window (NULL end) fills to it.
WINDOW_OPEN_END = 9999


def year_end(institution: Any) -> int:
    """Window end as a plain year; NULL (open) fills to WINDOW_OPEN_END."""
    end = institution.data_window_end
    return end if end is not None else WINDOW_OPEN_END


def author_works_join(institution_id: int, author_uuid: str) -> ColumnElement:
    """AuthorWork ↔ Work join for one author's works."""
    return and_(
        AuthorWork.institution_id == institution_id,
        AuthorWork.work_pure_uuid == Work.pure_uuid,
        AuthorWork.author_pure_uuid == author_uuid,
    )


def unit_author_join(institution_id: int) -> ColumnElement:
    """AuthorWork join keyed on each Author row (unit listings)."""
    return (AuthorWork.institution_id == institution_id) & (
        AuthorWork.author_pure_uuid == Author.pure_uuid
    )


def unit_work_join(institution_id: int) -> ColumnElement:
    """Work join completing unit_author_join."""
    return (Work.institution_id == institution_id) & (
        Work.pure_uuid == AuthorWork.work_pure_uuid
    )


def work_window(institution: Any) -> tuple[ColumnElement, ColumnElement]:
    """(year >= start, year <= end); an open end bounds at WINDOW_OPEN_END."""
    return (
        Work.year >= institution.data_window_start,
        Work.year <= year_end(institution),
    )


def strata_bound(column: Any, stratum: str) -> ColumnElement:
    """One stratum range condition; unknown strata raise (facet rebuilds
    iterate WORKS_STRATA, which is always valid)."""
    if stratum == "50+":
        return column >= 50
    return column.between(*_STRATA_BOUNDS[stratum])


def strata_cond(column: Any, values: list[str]) -> ColumnElement:
    """OR of stratum ranges; an unknown value matches nothing (no error)."""
    parts = []
    for value in values:
        if value == "50+":
            parts.append(column >= 50)
        elif bounds := _STRATA_BOUNDS.get(value):
            parts.append(column.between(*bounds))
    return or_(*parts) if parts else false()


def empty_year_buckets() -> dict[str, int]:
    """Fresh per-year OA counter dict in canonical bucket order."""
    return dict.fromkeys(YEAR_BUCKETS, 0)
