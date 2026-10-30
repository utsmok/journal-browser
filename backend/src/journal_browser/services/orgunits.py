"""Org-unit browsing: authors grouped by faculty or research_group.

The author set mirrors the authors list gate (institutions.
require_confirmed_affiliation); facets are authors-style query-time GROUP
BY under the drop-own-dimension rule. Unit membership is the non-empty
grouping column; works/APC/deal rollups bound to the institution's data
window."""

from typing import Any

from sqlalchemy import case, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import (
    ApcEvidence,
    Author,
    AuthorWork,
    Institution,
    Journal,
    JournalFlags,
    Work,
)
from .search import _like, _oa_type
from .works_query import (
    empty_year_buckets,
    strata_bound,
    strata_cond,
    unit_author_join,
    unit_work_join,
    work_window,
    WORKS_STRATA,
    YEAR_BUCKETS,
)

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
JOURNAL_CAP = 15
AUTHOR_CAP = 50
DEAL_USAGE_CAP = 8
TOPICS_PER_ITEM = 3
TOPICS_PER_DETAIL = 5

LEVELS = ("faculty", "group")
SORT_KEYS = ("relevance", "name", "authors", "works", "deal_works")


def _unit_key(level: str) -> Any:
    return Author.research_group if level == "group" else Author.faculty


def _author_base(iid: int, require_confirmed: bool) -> list[Any]:
    """Author-set gate shared by every unit query."""
    return [
        Author.institution_id == iid,
        *([Author.confirmed.is_(True)] if require_confirmed else []),
    ]


def _unit_rows(institution: Institution, level: str) -> Any:
    """Unit aggregates with deal/APC rollups outer-joined on the name."""
    iid = institution.id
    require_confirmed = institution.require_confirmed_affiliation
    key = _unit_key(level)
    agg_cols: list[Any] = [
        key.label("name"),
        func.max(Author.faculty).label("faculty"),
        func.count().label("n_authors"),
        func.coalesce(func.sum(Author.n_works), 0).label("n_works"),
    ]
    if level == "faculty":
        agg_cols.append(
            func.count(func.distinct(Author.research_group))
            .filter(Author.research_group.is_not(None), Author.research_group != "")
            .label("n_groups")
        )
    agg = (
        select(*agg_cols)
        .where(*_author_base(iid, require_confirmed), key.is_not(None), key != "")
        .group_by(key)
        .subquery()
    )

    def _edges(*, dois_only: bool) -> Any:
        """Unit authors' works (distinct per unit), window-bounded."""
        cols: list[Any] = [
            key.label("name"),
            Work.pure_uuid.label("work_uuid"),
            Work.doi_normalized.label("doi"),
            Work.journal_issn_l.label("issn_l"),
        ]
        conds = [
            *_author_base(iid, require_confirmed),
            key.is_not(None),
            key != "",
            Work.institution_id == iid,
            Work.retired_at.is_(None),
            *work_window(institution),
        ]
        if dois_only:
            conds.append(Work.doi_normalized.is_not(None))
        return (
            select(*cols)
            .select_from(Author)
            .join(
                AuthorWork,
                unit_author_join(iid),
            )
            .join(
                Work,
                unit_work_join(iid),
            )
            .where(*conds)
            .distinct()
            .subquery()
        )

    edges = _edges(dois_only=False)
    deal_agg = (
        select(edges.c.name.label("name"), func.count().label("deal_works"))
        .join(
            JournalFlags,
            (JournalFlags.institution_id == iid) & (JournalFlags.issn_l == edges.c.issn_l),
        )
        .where(JournalFlags.deal_covered.is_(True))
        .group_by(edges.c.name)
        .subquery()
    )
    doi_edges = _edges(dois_only=True)
    # Latest-period evidence per (unit, doi); euro null at that period
    # contributes nothing (contract: euro summed over latest period per doi).
    ranked = (
        select(
            doi_edges.c.name.label("name"),
            ApcEvidence.euro.label("euro"),
            func.row_number()
            .over(
                partition_by=(doi_edges.c.name, doi_edges.c.doi),
                order_by=(ApcEvidence.period.desc().nulls_last(), ApcEvidence.id.desc()),
            )
            .label("rn"),
        )
        .join(
            ApcEvidence,
            (ApcEvidence.institution_id == iid) & (ApcEvidence.doi == doi_edges.c.doi),
        )
        .subquery()
    )
    best = (
        select(ranked.c.name.label("name"), ranked.c.euro.label("euro"))
        .where(ranked.c.rn == 1)
        .subquery()
    )
    apc_agg = (
        select(
            best.c.name.label("name"),
            func.coalesce(func.sum(best.c.euro), 0).label("apc_euro_total"),
            func.count(best.c.euro).label("apc_n"),
        )
        .group_by(best.c.name)
        .subquery()
    )
    return (
        select(
            agg,
            func.coalesce(deal_agg.c.deal_works, 0).label("deal_works"),
            func.coalesce(apc_agg.c.apc_euro_total, 0).label("apc_euro_total"),
            func.coalesce(apc_agg.c.apc_n, 0).label("apc_n"),
        )
        .select_from(
            agg.join(deal_agg, deal_agg.c.name == agg.c.name, isouter=True).join(
                apc_agg, apc_agg.c.name == agg.c.name, isouter=True
            )
        )
        .subquery()
    )


def _order(units: Any, sort: str, q: str | None) -> tuple[Any, str]:
    """(order expression, natural direction)."""
    if sort == "name":
        return func.lower(units.c.name), "asc"
    if sort == "authors":
        return units.c.n_authors, "desc"
    if sort == "deal_works":
        return units.c.deal_works, "desc"
    if sort == "relevance" and q and q.strip():
        tier = case((units.c.name.ilike(f"{_like(q.strip())}%", escape="\\"), 1), else_=0)
        return tier, "desc"
    return units.c.n_works, "desc"  # works, and relevance without q


def _item(row: Any, level: str, topics: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "level": level,
        "name": row.name,
        # The faculty attribute is only set on the group level (contract).
        "faculty": row.faculty if level == "group" else None,
        "n_authors": row.n_authors,
        "n_works": int(row.n_works or 0),
        "n_groups": row.n_groups if level == "faculty" else None,
        "deal_works": int(row.deal_works),
        "apc_euro_total": float(row.apc_euro_total),
        "apc_n": int(row.apc_n),
        "topics": topics,
    }


async def _unit_topics(
    session: AsyncSession,
    iid: int,
    level: str,
    require_confirmed: bool,
    names: list[str] | None,
    top: int,
) -> dict[str, list[dict[str, Any]]]:
    """Author-count topic distribution per unit (authors.primary_topic)."""
    key = _unit_key(level)
    conds = [*_author_base(iid, require_confirmed), Author.primary_topic.is_not(None)]
    if names:
        conds.append(key.in_(names))
    rows = (
        await session.execute(
            select(key.label("name"), Author.primary_topic.label("topic"), func.count().label("n"))
            .where(*conds)
            .group_by(key, Author.primary_topic)
        )
    ).all()
    counts: dict[str, list[tuple[str, int]]] = {}
    for row in rows:
        counts.setdefault(row.name, []).append((row.topic, row.n))
    return {
        name: [
            {"name": topic, "n": n}
            for topic, n in sorted(rows_, key=lambda kv: (-kv[1], kv[0]))[:top]
        ]
        for name, rows_ in counts.items()
    }


async def search_orgunits(
    session: AsyncSession,
    *,
    institution: Institution,
    level: str,
    q: str | None = None,
    faculty: list[str] | None = None,
    works: list[str] | None = None,
    uses_deals: bool | None = None,
    sort: str | None = None,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
    include_facets: bool = True,
) -> dict[str, Any]:
    """Unit roster for one institution: total is the filter match count,
    items the offset/limit page of the sorted matches (default sort
    relevance-with-q, else works desc)."""
    iid = institution.id
    units = _unit_rows(institution, level)
    conds: dict[str, Any] = {}
    if faculty and level == "group":
        conds["faculty"] = units.c.faculty.in_(faculty)
    if works:
        conds["works"] = strata_cond(units.c.n_works, works)
    if uses_deals is True:
        conds["uses_deals"] = units.c.deal_works > 0
    q_cond = (
        units.c.name.ilike(f"%{_like(q.strip())}%", escape="\\") if q and q.strip() else None
    )
    where = list(conds.values()) + ([q_cond] if q_cond is not None else [])
    total = await session.scalar(select(func.count()).select_from(units).where(*where)) or 0

    if sort is None:
        sort = "relevance" if q_cond is not None else "works"
    order_col, direction = _order(units, sort, q)
    order_by = [order_col.desc(), func.lower(units.c.name), units.c.name]
    if direction == "asc":
        order_by[0] = order_col.asc()
    page_rows = (
        await session.execute(
            select(units)
            .where(*where)
            .order_by(*order_by)
            .offset(offset)
            .limit(min(limit, MAX_LIMIT))
        )
    ).all()

    require_confirmed = institution.require_confirmed_affiliation
    topics = await _unit_topics(
        session, iid, level, require_confirmed, [r.name for r in page_rows], TOPICS_PER_ITEM
    )
    items = [_item(r, level, topics.get(r.name, [])) for r in page_rows]

    facets: dict[str, dict[str, int]] = {}
    if include_facets:
        others = [c for key_, c in conds.items() if key_ != "faculty"] + (
            [q_cond] if q_cond is not None else []
        )
        if level == "group":
            rows_ = (
                await session.execute(
                    select(units.c.faculty, func.count())
                    .where(*others, units.c.faculty.is_not(None))
                    .group_by(units.c.faculty)
                    .order_by(func.count().desc(), units.c.faculty)
                )
            ).all()
            facets["faculty"] = {r.faculty: int(r[1]) for r in rows_}
        others = [c for key_, c in conds.items() if key_ != "works"] + (
            [q_cond] if q_cond is not None else []
        )
        row = (
            await session.execute(
                select(
                    *[
                        func.count().filter(strata_bound(units.c.n_works, stratum))
                        for stratum in WORKS_STRATA
                    ]
                )
                .select_from(units)
                .where(*others)
            )
        ).one()
        facets["size"] = dict(zip(WORKS_STRATA, (int(v or 0) for v in row), strict=True))
        others = [c for key_, c in conds.items() if key_ != "uses_deals"] + (
            [q_cond] if q_cond is not None else []
        )
        row = (
            await session.execute(
                select(
                    func.count().filter(units.c.deal_works > 0),
                    func.count().filter(units.c.deal_works == 0),
                )
                .select_from(units)
                .where(*others)
            )
        ).one()
        facets["uses_deals"] = {"yes": int(row[0] or 0), "no": int(row[1] or 0)}
    return {"level": level, "items": items, "total": int(total), "facets": facets}


async def orgunit_detail(
    session: AsyncSession, institution: Institution, level: str, name: str
) -> dict[str, Any] | None:
    """Full unit bundle; None = unknown unit (404 upstream)."""
    iid = institution.id
    require_confirmed = institution.require_confirmed_affiliation
    units = _unit_rows(institution, level)
    unit_row = (
        await session.execute(select(units).where(units.c.name == name))
    ).one_or_none()
    if unit_row is None:
        return None

    topics_by_unit = await _unit_topics(
        session, iid, level, require_confirmed, [name], TOPICS_PER_DETAIL
    )
    topics = topics_by_unit[name]

    groups = None
    if level == "faculty":
        child = await search_orgunits(
            session,
            institution=institution,
            level="group",
            faculty=[name],
            sort="works",
            limit=MAX_LIMIT,
            include_facets=False,
        )
        groups = child["items"]

    membership = [*_author_base(iid, require_confirmed), _unit_key(level) == name]

    # The unit's venues: distinct works per journal, window-bounded; the
    # admin ignore-list removes venues just like the author profile.
    ignored = get_settings().ignored_issns
    flags = (
        select(JournalFlags.issn_l, JournalFlags.deal_covered)
        .where(JournalFlags.institution_id == iid)
        .subquery()
    )
    journal_rows = (
        await session.execute(
            select(
                Work.journal_issn_l.label("issn_l"),
                Journal.title.label("title"),
                func.count(func.distinct(Work.pure_uuid)).label("n_works"),
                flags.c.deal_covered,
                _oa_type(flags.c.deal_covered).label("oa_type"),
                Journal.latest_quartile.label("quartile"),
            )
            .select_from(Author)
            .join(
                AuthorWork,
                unit_author_join(iid),
            )
            .join(
                Work,
                unit_work_join(iid),
            )
            .join(Journal, Journal.issn_l == Work.journal_issn_l)
            .join(flags, flags.c.issn_l == Journal.issn_l)
            .where(
                *membership,
                Work.retired_at.is_(None),
                *work_window(institution),
                *([Journal.issn_l.not_in(sorted(set(ignored)))] if ignored else []),
            )
            .group_by(
                Work.journal_issn_l,
                Journal.issn_l,
                Journal.title,
                Journal.is_in_doaj,
                Journal.latest_quartile,
                flags.c.deal_covered,
            )
            .order_by(func.count(func.distinct(Work.pure_uuid)).desc(), Work.journal_issn_l)
            .limit(JOURNAL_CAP)
        )
    ).all()

    author_rows = (
        await session.execute(
            select(
                Author.pure_uuid,
                Author.name,
                Author.n_works,
                Author.orcid,
                Author.primary_topic,
            )
            .where(*membership)
            .order_by(Author.n_works.desc(), func.lower(Author.name), Author.pure_uuid)
            .limit(AUTHOR_CAP)
        )
    ).all()

    year_rows = (
        await session.execute(
            select(Work.year, Work.oa_status, func.count().label("n"))
            .select_from(Author)
            .join(
                AuthorWork,
                unit_author_join(iid),
            )
            .join(
                Work,
                unit_work_join(iid),
            )
            .where(
                *membership,
                Work.retired_at.is_(None),
                *work_window(institution),
            )
            .group_by(Work.year, Work.oa_status)
        )
    ).all()
    by_year: dict[int, dict[str, int]] = {}
    for row in year_rows:
        bucket = by_year.setdefault(row.year, {"year": row.year, "total": 0, **empty_year_buckets()})
        bucket["total"] += row.n
        if row.oa_status in YEAR_BUCKETS:
            bucket[row.oa_status] += row.n
    works_by_year = [
        {
            "year": year,
            "works_count": by_year[year]["total"],
            "works_count_source": "pure_canon",
            **{f"oa_{status}": by_year[year][status] for status in YEAR_BUCKETS},
        }
        for year in sorted(by_year, reverse=True)
    ]

    # Deal-covered output grouped by agreement, falling back to the
    # journal's publisher when the evidence carries no agreement label.
    unit_works = (
        select(
            Work.pure_uuid.label("work_uuid"),
            Work.doi_normalized.label("doi"),
            Journal.publisher_name.label("publisher"),
        )
        .select_from(Author)
        .join(AuthorWork, unit_author_join(iid))
        .join(Work, unit_work_join(iid))
        .join(
            JournalFlags,
            (JournalFlags.institution_id == iid)
            & (JournalFlags.issn_l == Work.journal_issn_l)
            & JournalFlags.deal_covered.is_(True),
        )
        .outerjoin(Journal, Journal.issn_l == Work.journal_issn_l)
        .where(
            *membership,
            Work.retired_at.is_(None),
            *work_window(institution),
        )
        .subquery()
    )
    ranked = (
        select(
            unit_works.c.work_uuid,
            unit_works.c.publisher,
            ApcEvidence.agreement.label("agreement"),
            ApcEvidence.euro.label("euro"),
            func.row_number()
            .over(
                partition_by=unit_works.c.work_uuid,
                order_by=(ApcEvidence.period.desc().nulls_last(), ApcEvidence.id.desc()),
            )
            .label("rn"),
        )
        .outerjoin(
            ApcEvidence,
            (ApcEvidence.institution_id == iid) & (ApcEvidence.doi == unit_works.c.doi),
        )
        .subquery()
    )
    best = (
        select(
            ranked.c.work_uuid,
            ranked.c.publisher,
            ranked.c.agreement,
            ranked.c.euro,
        )
        .where(ranked.c.rn == 1)
        .subquery()
    )
    label = func.coalesce(func.nullif(best.c.agreement, ""), best.c.publisher)
    usage_rows = (
        await session.execute(
            select(
                label.label("label"),
                func.count().label("n_works"),
                func.coalesce(func.sum(best.c.euro), 0).label("euro"),
            )
            .select_from(best)
            .where(label.is_not(None))
            .group_by(label)
            .order_by(func.count().desc(), label)
            .limit(DEAL_USAGE_CAP)
        )
    ).all()

    return {
        "unit": _item(unit_row, level, topics),
        "groups": groups,
        "journals": [
            {
                "issn_l": r.issn_l,
                "title": r.title,
                "n_works": r.n_works,
                "deal_covered": bool(r.deal_covered),
                "oa_type": r.oa_type,
                "quartile": r.quartile,
            }
            for r in journal_rows
        ],
        "authors": [
            {
                "pure_uuid": r.pure_uuid,
                "name": r.name,
                "n_works": r.n_works,
                "orcid": r.orcid,
                "primary_topic": r.primary_topic,
            }
            for r in author_rows
        ],
        "works_by_year": works_by_year,
        "deal_usage": [
            {"label": r.label, "n_works": int(r.n_works), "euro": float(r.euro)}
            for r in usage_rows
        ],
    }
