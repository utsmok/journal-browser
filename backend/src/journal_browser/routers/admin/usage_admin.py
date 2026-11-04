"""Admin usage summary: aggregate view over usage_events.

Read-only rollups for the admin panel — what is viewed, searched, and
which errors clients hit. Plain selects here on purpose: one admin-only
read model, not a service surface.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import desc, func, select

from ...models import UsageEvent
from ...schemas import (
    UsageCountryCount,
    UsageDayCount,
    UsageErrorGroup,
    UsageSearchSplit,
    UsageSummaryOut,
    UsageTopPath,
    UsageTopQuery,
    UsageTopRef,
)
from .auth import AdminDep, SessionDep

router = APIRouter(prefix="/admin", tags=["admin"])

TOP_LIMIT = 20


@router.get("/usage/summary", response_model=UsageSummaryOut)
async def usage_summary(
    session: SessionDep,
    _: AdminDep,
    days: Annotated[int, Query()] = 30,
) -> UsageSummaryOut:
    days = max(1, min(365, days))
    since = datetime.now(UTC) - timedelta(days=days)
    window = UsageEvent.ts >= since

    totals = dict(
        (
            await session.execute(
                select(UsageEvent.event_type, func.count())
                .where(window)
                .group_by(UsageEvent.event_type)
            )
        ).all()
    )

    daily: dict[str, dict[str, int]] = {}
    day_rows = await session.execute(
        select(func.date(UsageEvent.ts), UsageEvent.event_type, func.count())
        .where(window)
        .group_by(func.date(UsageEvent.ts), UsageEvent.event_type)
        .order_by(func.date(UsageEvent.ts))
    )
    for day, event_type, n in day_rows:
        daily.setdefault(str(day), {"page_view": 0, "search": 0, "error": 0})[event_type] = n

    path_rows = await session.execute(
        select(UsageEvent.path, func.count(), func.avg(UsageEvent.duration_ms))
        .where(window, UsageEvent.event_type == "page_view")
        .group_by(UsageEvent.path)
        .order_by(desc(func.count()))
        .limit(TOP_LIMIT)
    )
    top_paths = [
        UsageTopPath(
            path=path,
            page_views=n,
            avg_duration_ms=round(avg, 1) if avg is not None else None,
        )
        for path, n, avg in path_rows
    ]

    query_rows = await session.execute(
        select(
            UsageEvent.query,
            func.count(),
            func.count().filter(UsageEvent.results_count == 0),
        )
        .where(window, UsageEvent.event_type == "search", UsageEvent.query.is_not(None))
        .group_by(UsageEvent.query)
        .order_by(desc(func.count()))
        .limit(TOP_LIMIT)
    )
    top_queries = [
        UsageTopQuery(query=query, count=n, zero_share=(zero / n if n else 0.0))
        for query, n, zero in query_rows
        if query is not None
    ]

    ref_rows = await session.execute(
        select(UsageEvent.ref_type, UsageEvent.ref_id, func.count())
        .where(window, UsageEvent.ref_type.is_not(None))
        .group_by(UsageEvent.ref_type, UsageEvent.ref_id)
        .order_by(desc(func.count()))
        .limit(TOP_LIMIT)
    )
    top_refs = [
        UsageTopRef(ref_type=ref_type, ref_id=ref_id, count=n)
        for ref_type, ref_id, n in ref_rows
        if ref_type is not None and ref_id is not None
    ]

    error_rows = await session.execute(
        select(
            UsageEvent.source,
            UsageEvent.status,
            UsageEvent.message,
            func.count(),
            func.max(UsageEvent.ts),
        )
        .where(window, UsageEvent.event_type == "error")
        .group_by(UsageEvent.source, UsageEvent.status, UsageEvent.message)
        .order_by(desc(func.count()))
        .limit(TOP_LIMIT)
    )
    errors = [
        UsageErrorGroup(source=source, status=status, message=message, count=n, last_ts=last_ts)
        for source, status, message, n, last_ts in error_rows
    ]

    country_rows = await session.execute(
        select(UsageEvent.country, func.count())
        .where(window, UsageEvent.country.is_not(None))
        .group_by(UsageEvent.country)
        .order_by(desc(func.count()))
        .limit(10)
    )
    countries = [
        UsageCountryCount(country=country, count=n)
        for country, n in country_rows
        if country is not None
    ]

    sessions = await session.scalar(
        select(func.count(func.distinct(UsageEvent.session_id))).where(window)
    )

    browse, queries = (
        await session.execute(
            select(
                func.count().filter(UsageEvent.is_browse),
                func.count().filter(UsageEvent.query.is_not(None)),
            ).where(window, UsageEvent.event_type == "search")
        )
    ).one()

    return UsageSummaryOut(
        days=days,
        totals=totals,
        searches=UsageSearchSplit(browse=browse, queries=queries),
        daily=[UsageDayCount(date=day, **counts) for day, counts in daily.items()],
        top_paths=top_paths,
        top_queries=top_queries,
        top_refs=top_refs,
        errors=errors,
        countries=countries,
        sessions=sessions or 0,
    )
