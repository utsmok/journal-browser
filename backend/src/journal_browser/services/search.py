"""Journal search: Postgres FTS + facets + keyset pagination."""

import base64
import json
from typing import Any

from sqlalchemy import Numeric, String, and_, case, cast, func, or_, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    Deal,
    DealInstitution,
    DealJournal,
    Institution,
    InstitutionWorksStats,
    Journal,
    ScimagojrMetric,
)

SortKey = str  # relevance | title | institution_works | 2yr_mean_citedness

_HOME_INST = select(Institution.id).where(Institution.is_home.is_(True)).scalar_subquery()

#: Current open access deals covering the home institution.
DEAL_COVERED = (
    select(DealJournal.issn_l)
    .join(Deal, Deal.id == DealJournal.deal_id)
    .join(DealInstitution, DealInstitution.deal_id == Deal.id)
    .where(
        DealJournal.issn_l == Journal.issn_l,
        Deal.status == "current",
        DealInstitution.institution_id == _HOME_INST,
    )
    .exists()
)

TWENTE_WORKS = (
    select(func.coalesce(func.sum(InstitutionWorksStats.works_count), 0))
    .where(
        InstitutionWorksStats.issn_l == Journal.issn_l,
        InstitutionWorksStats.institution_id == _HOME_INST,
    )
    .correlate(Journal)
    .scalar_subquery()
)

LATEST_QUARTILE = (
    select(ScimagojrMetric.best_quartile)
    .where(ScimagojrMetric.issn_l == Journal.issn_l)
    .order_by(ScimagojrMetric.year.desc())
    .limit(1)
    .correlate(Journal)
    .scalar_subquery()
)


def parse_cursor(cursor: str | None) -> tuple[str, str] | None:
    if not cursor:
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return str(data["v"]), str(data["k"])
    except Exception:
        return None


def encode_cursor(value: Any, issn_l: str) -> str:
    raw = json.dumps({"v": value, "k": issn_l}, default=str)
    return base64.urlsafe_b64encode(raw.encode()).decode()


def quality_bar_clause() -> Any:
    """Corpus quality bar (decisions.md #12): type=journal AND
    (DOAJ OR Scimago OR deal coverage OR active since 2020)."""
    J = Journal
    covered = DEAL_COVERED.correlate(J)
    return and_(
        J.type == "journal",
        J.issn_l.is_not(None),
        or_(
            J.is_in_doaj.is_(True),
            J.in_scimago.is_(True),
            covered,
            J.is_active_recently.is_(True),
        ),
    )


def base_query(
    *,
    q: str | None = None,
    deal: str = "any",
    oa: bool | None = None,
    doaj: bool | None = None,
    quartile: str | None = None,
    topic: str | None = None,
    scope: str = "quality",
):
    """Filtered select with computed columns; search + facet counts share it."""
    J = Journal
    # OpenAlex publishes this metric as "two_yr_mean_citedness".
    twoyr = cast(J.summary_stats.op("->>")("two_yr_mean_citedness"), Numeric).label("twoyr")
    covered = DEAL_COVERED.correlate(J).label("deal_covered")
    if q:
        qstr = q.strip()
        # Relevance = title-prefix match tier + FTS rank + prominence nudge
        # from corpus size (works_count). One expression so keyset
        # pagination can compare (rank, issn_l) tuples; the tier spacing
        # dwarfs the other ranges, so title matches always sort first, and
        # within a tier an established flagship outranks a niche journal
        # with a momentarily higher citedness metric.
        rank = (
            case((J.title.ilike(f"{qstr}%"), 100.0), else_=0.0)
            + func.ts_rank(J.search_vector, func.websearch_to_tsquery(text("'english'"), qstr))
            + func.least(func.coalesce(J.works_count, 0), 100000) * 0.00001
        ).label("rank")
    else:
        rank = cast(text("0"), Numeric).label("rank")
    query = select(
        J.issn_l,
        J.title,
        J.publisher_name,
        J.is_oa,
        J.is_in_doaj,
        J.in_scimago,
        J.last_active_year,
        quality_bar_clause().label("in_quality_bar"),
        covered,
        TWENTE_WORKS.label("twente_works"),
        LATEST_QUARTILE.label("quartile"),
        twoyr,
        rank,
    )
    if scope == "quality":
        query = query.where(quality_bar_clause())
    if q:
        issn = q.strip().upper()
        tsq = func.websearch_to_tsquery(text("'english'"), q)
        query = query.where(
            or_(
                J.search_vector.op("@@")(tsq),
                J.issn_l == issn,
                J.search_text.ilike(f"{q}%"),
            )
        )
    if deal == "covered":
        query = query.where(covered)
    elif deal == "not_covered":
        query = query.where(~covered)
    if oa is not None:
        query = query.where(J.is_oa.is_(oa))
    if doaj is not None:
        query = query.where(J.is_in_doaj.is_(doaj))
    if quartile in {"Q1", "Q2", "Q3", "Q4"}:
        query = query.where(quartile == LATEST_QUARTILE)
    if topic:
        query = query.where(Journal.topics.op("@>")(f'[{{"display_name": "{topic}"}}]'))
    return query


def _order(sort: SortKey, subq: Any) -> tuple[Any, str]:
    """Returns (order expression, direction)."""
    if sort == "title":
        return func.lower(func.coalesce(subq.c.title, "")), "asc"
    if sort == "institution_works":
        return func.coalesce(subq.c.twente_works, 0), "desc"
    if sort == "2yr_mean_citedness":
        return func.coalesce(subq.c.twoyr, 0), "desc"
    return func.coalesce(subq.c.rank, 0), "desc"  # relevance


async def search_journals(
    session: AsyncSession,
    *,
    q: str | None = None,
    deal: str = "any",
    oa: bool | None = None,
    doaj: bool | None = None,
    quartile: str | None = None,
    topic: str | None = None,
    sort: SortKey = "relevance",
    cursor: str | None = None,
    limit: int = 20,
    scope: str = "quality",
) -> dict[str, Any]:
    subq = base_query(
        q=q, deal=deal, oa=oa, doaj=doaj, quartile=quartile, topic=topic, scope=scope
    ).subquery()
    total = await session.scalar(select(func.count()).select_from(subq)) or 0

    order_col, direction = _order(sort, subq)
    tiebreak = subq.c.issn_l
    keyset = parse_cursor(cursor)

    if direction == "desc":
        page_q = select(subq).order_by(order_col.desc(), tiebreak.desc())
        if keyset:
            page_q = page_q.where(
                tuple_(order_col, tiebreak) < tuple_(cast(keyset[0], Numeric), keyset[1])
            )
    else:
        page_q = select(subq).order_by(order_col.asc(), tiebreak.asc())
        if keyset:
            page_q = page_q.where(
                tuple_(order_col, tiebreak) > tuple_(cast(keyset[0], String), keyset[1])
            )
    rows = (await session.execute(page_q.limit(limit + 1))).all()

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        value_col = {
            "title": "title",
            "institution_works": "twente_works",
            "2yr_mean_citedness": "twoyr",
            "relevance": "rank",
        }[sort]
        value = getattr(last, value_col)
        next_cursor = encode_cursor(
            float(value) if isinstance(value, (int, float)) else value, last.issn_l
        )

    items = []
    for row in rows:
        item = dict(row._mapping)
        item["twoyr_mean_citedness"] = (
            float(item.pop("twoyr")) if item.get("twoyr") is not None else None
        )
        item.pop("rank", None)
        items.append(item)

    facets = await facet_counts(session, q=q, oa=oa, doaj=doaj, quartile=quartile, scope=scope)
    return {
        "items": items,
        "total": int(total),
        "next_cursor": next_cursor,
        "facets": facets,
    }


async def facet_counts(
    session: AsyncSession,
    *,
    q: str | None,
    oa: bool | None,
    doaj: bool | None,
    quartile: str | None,
    scope: str = "quality",
) -> dict[str, dict[str, int]]:
    """Facet counts over the query-filtered set (each facet's own filter
    excluded); the active scope always applies. Deal counts always reflect
    the home institution."""
    subq = base_query(q=q, oa=oa, doaj=doaj, quartile=quartile, scope=scope).subquery()
    row = (
        await session.execute(
            select(
                func.count(),
                func.sum(case((subq.c.deal_covered.is_(True), 1), else_=0)),
                func.sum(case((subq.c.is_oa.is_(True), 1), else_=0)),
                func.sum(case((subq.c.is_in_doaj.is_(True), 1), else_=0)),
                func.sum(case((subq.c.quartile == "Q1", 1), else_=0)),
                func.sum(case((subq.c.quartile == "Q2", 1), else_=0)),
                func.sum(case((subq.c.quartile == "Q3", 1), else_=0)),
                func.sum(case((subq.c.quartile == "Q4", 1), else_=0)),
            )
        )
    ).one()
    total = int(row[0] or 0)
    facets: dict[str, dict[str, int]] = {
        "deal_coverage": {
            "covered": int(row[1] or 0),
            "not_covered": total - int(row[1] or 0),
        },
        "oa": {"true": int(row[2] or 0), "false": total - int(row[2] or 0)},
        "doaj": {"true": int(row[3] or 0), "false": total - int(row[3] or 0)},
        "quartile": {
            "Q1": int(row[4] or 0),
            "Q2": int(row[5] or 0),
            "Q3": int(row[6] or 0),
            "Q4": int(row[7] or 0),
        },
    }
    elem = func.jsonb_array_elements(
        func.coalesce(Journal.topics, text("'[]'::jsonb"))
    ).table_valued("value", name="t")
    topic_subq = base_query(q=q, oa=oa, doaj=doaj, quartile=quartile, scope=scope).subquery()
    topic_rows = await session.execute(
        select(
            elem.c.value.op("->>")("display_name").label("topic"),
            func.count().label("n"),
        )
        .select_from(topic_subq, Journal, elem)
        .where(Journal.issn_l == topic_subq.c.issn_l)
        .group_by(text("1"))
        .order_by(text("2 DESC"))
        .limit(15)
    )
    facets["topic"] = {row.topic: int(row.n) for row in topic_rows}
    return facets
