"""Journal search: Postgres FTS + facets + keyset pagination."""

import base64
import json
from typing import Any

from sqlalchemy import Numeric, String, case, cast, func, or_, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Journal

SortKey = str  # relevance | title | institution_works | 2yr_mean_citedness

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


#: Corpus cutoff (owner decision 2026-10-23, superseding decision 12):
#: journals with <= 3 works in the 2020+ window are presentation-excluded.
WORKS_CUTOFF = Journal.works_2020_plus > 3


def base_query(
    *,
    q: str | None = None,
    deal: str = "any",
    oa: bool | None = None,
    doaj: bool | None = None,
    quartile: str | None = None,
    topic: str | None = None,
):
    """Filtered select with computed columns; search + facet counts share it.

    The corpus cutoff (works_2020_plus > 3) always applies."""
    J = Journal
    # OpenAlex publishes this metric as "two_yr_mean_citedness".
    twoyr = cast(J.summary_stats.op("->>")("two_yr_mean_citedness"), Numeric).label("twoyr")
    covered = J.deal_covered_home.label("deal_covered")
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
        covered,
        func.coalesce(J.home_works_count, 0).label("twente_works"),
        J.latest_quartile.label("quartile"),
        twoyr,
        rank,
    ).where(WORKS_CUTOFF, J.type == "journal", J.issn_l.is_not(None))
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
        query = query.where(J.deal_covered_home.is_(True))
    elif deal == "not_covered":
        query = query.where(J.deal_covered_home.is_(False))
    if oa is not None:
        query = query.where(J.is_oa.is_(oa))
    if doaj is not None:
        query = query.where(J.is_in_doaj.is_(doaj))
    if quartile in {"Q1", "Q2", "Q3", "Q4"}:
        query = query.where(J.latest_quartile == quartile)
    if topic:
        query = query.where(J.topics.contains([{"display_name": topic}]))
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
) -> dict[str, Any]:
    subq = base_query(
        q=q, deal=deal, oa=oa, doaj=doaj, quartile=quartile, topic=topic
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

    facets = await facet_counts(
        session, q=q, deal=deal, oa=oa, doaj=doaj, quartile=quartile, topic=topic
    )
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
    deal: str,
    oa: bool | None,
    doaj: bool | None,
    quartile: str | None,
    topic: str | None,
) -> dict[str, dict[str, int]]:
    """Facet counts over the query-filtered set. Each facet's own filter is
    excluded so a chip shows what selecting it would yield; all other active
    filters apply. The corpus cutoff always applies, and deal counts always
    reflect the home institution."""

    async def _one(subquery: Any, *counts: Any) -> tuple[int, list[int]]:
        row = (
            await session.execute(
                select(func.count(), *[func.sum(case((c, 1), else_=0)) for c in counts])
            )
        ).one()
        return int(row[0] or 0), [int(v or 0) for v in row[1:]]

    d = base_query(q=q, oa=oa, doaj=doaj, quartile=quartile, topic=topic).subquery()
    d_total, (d_covered,) = await _one(d, d.c.deal_covered.is_(True))
    o = base_query(q=q, deal=deal, doaj=doaj, quartile=quartile, topic=topic).subquery()
    o_total, (o_true,) = await _one(o, o.c.is_oa.is_(True))
    dj = base_query(q=q, deal=deal, oa=oa, quartile=quartile, topic=topic).subquery()
    dj_total, (dj_true,) = await _one(dj, dj.c.is_in_doaj.is_(True))
    qt = base_query(q=q, deal=deal, oa=oa, doaj=doaj, topic=topic).subquery()
    qt_total, (q1, q2, q3, q4) = await _one(
        qt,
        qt.c.quartile == "Q1",
        qt.c.quartile == "Q2",
        qt.c.quartile == "Q3",
        qt.c.quartile == "Q4",
    )
    facets: dict[str, dict[str, int]] = {
        "deal_coverage": {"covered": d_covered, "not_covered": d_total - d_covered},
        "oa": {"true": o_true, "false": o_total - o_true},
        "doaj": {"true": dj_true, "false": dj_total - dj_true},
        "quartile": {"Q1": q1, "Q2": q2, "Q3": q3, "Q4": q4},
    }
    elem = func.jsonb_array_elements(
        func.coalesce(Journal.topics, text("'[]'::jsonb"))
    ).table_valued("value", name="t")
    topic_subq = base_query(q=q, deal=deal, oa=oa, doaj=doaj, quartile=quartile).subquery()
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
