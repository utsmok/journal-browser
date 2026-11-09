"""Shared author-works query fragments: joins, window bounds, strata, and
the OA year buckets. New queries touching author works import these; inline
copies get rejected in review."""

from typing import Any

from sqlalchemy import and_, false, func, or_
from sqlalchemy.sql.elements import ColumnElement

from ..config import EXCLUDED_WORK_TYPES
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


def clamped_year_range(
    institution: Any,
    year_from: int | None,
    year_to: int | None,
) -> tuple[int, int] | None:
    """Explicit publication-year range clamped inside the institution's
    data window; None when no bound was passed (the default view, exactly
    today's behavior).

    Both bounds come back concrete so callers can replace the window gates
    wholesale when a range is active. An open window end fills to
    WINDOW_OPEN_END like year_end; from > to raises ValueError (the
    app-level handler answers 400)."""
    if year_from is None and year_to is None:
        return None
    if year_from is not None and year_to is not None and year_from > year_to:
        raise ValueError("year_from must not be after year_to")
    start = institution.data_window_start
    end = year_end(institution)
    lo = start if year_from is None else max(year_from, start)
    hi = end if year_to is None else min(year_to, end)
    return (lo, hi)


def work_type_not_excluded(column: Any) -> ColumnElement:
    """SQL twin of config.work_type_excluded: the normalized work type
    (lower-cased, info:eu-repo/semantics/ stripped, hyphens collapsed) is
    not one of the never-journal-output types. One definition for every
    query that must describe the same population as the pure_canon stats
    (write_pure_canon_stats was the first consumer)."""
    normalized = func.lower(
        func.replace(
            func.replace(func.coalesce(column, ""), "info:eu-repo/semantics/", ""), "-", ""
        )
    )
    return normalized.not_in(sorted(EXCLUDED_WORK_TYPES))


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
    return (Work.institution_id == institution_id) & (Work.pure_uuid == AuthorWork.work_pure_uuid)


def work_window(institution: Any) -> tuple[ColumnElement, ColumnElement]:
    """(year >= start, year <= end); an open end bounds at WINDOW_OPEN_END."""
    return (
        Work.year >= institution.data_window_start,
        Work.year <= year_end(institution),
    )


def work_year_window(
    institution: Any, year_range: tuple[int, int] | None
) -> tuple[ColumnElement, ColumnElement]:
    """Work year bounds for the explicit clamped range, or work_window's
    default when no range is active. One definition for every works-list
    query the publication-year filter threads through."""
    if year_range is None:
        return work_window(institution)
    lo, hi = year_range
    return (Work.year >= lo, Work.year <= hi)


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


def strata_match(n_works: int, values: list[str]) -> bool:
    """Python twin of strata_cond for snapshot-filtered serving; same
    unknown-value-matches-nothing rule."""
    for value in values:
        if value == "50+" and n_works >= 50:
            return True
        if (bounds := _STRATA_BOUNDS.get(value)) and bounds[0] <= n_works <= bounds[1]:
            return True
    return False


def empty_year_buckets() -> dict[str, int]:
    """Fresh per-year OA counter dict in canonical bucket order."""
    return dict.fromkeys(YEAR_BUCKETS, 0)
