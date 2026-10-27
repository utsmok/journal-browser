"""Publisher browsing: browsable journals aggregated per publisher_name.

Mirror of the journal/author surfaces: the browsable cutoffs are the same
predicates as search.base_query (type='journal', per-institution
works_window_plus > 3, not browse_excluded, not admin-ignored), facets are
authors-style query-time GROUP BY (no cache) under the drop-own-dimension
rule. Grouping key is journals.publisher_name — publishers.id only covers
deal publishers."""

import warnings
from typing import Any

from sqlalchemy import case, exists, func, or_, select, text
from sqlalchemy import exc as sa_exc
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..harvest.authors import topic_mass
from ..models import (
    Deal,
    DealInstitution,
    DealJournal,
    Institution,
    InstitutionWorksStats,
    Journal,
    JournalFlags,
    Publisher,
)
from .search import APC_SHOWN, OA_TYPES, _like, _oa_type, search_journals

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
JOURNAL_CAP = 200
TOPIC_FACET_LIMIT = 10
TOPICS_PER_ITEM = 3
TOPICS_PER_DETAIL = 5

QUARTILES = ("Q1", "Q2", "Q3", "Q4")
SIZE_BUCKETS = ("1", "2-4", "5-9", "10+")
SORT_KEYS = ("relevance", "name", "journals", "works", "deals", "apc")


def _journal_rows(institution_id: int) -> Any:
    """Browsable journals with every column the publisher aggregates read."""
    J, F = Journal, JournalFlags
    ignored = get_settings().ignored_issns
    return (
        select(
            J.issn_l,
            J.publisher_name,
            F.works_count.label("works"),
            F.deal_covered.label("deal_covered"),
            _oa_type(F.deal_covered).label("oa_type"),
            J.latest_quartile.label("quartile"),
            APC_SHOWN.label("apc_any"),
            J.latest_apc_euro.label("apc_euro"),
            J.topics,
        )
        .join(F, (F.institution_id == institution_id) & (F.issn_l == J.issn_l))
        .where(
            J.type == "journal",
            J.issn_l.is_not(None),
            F.works_window_plus > 3,
            F.browse_excluded.is_not(True),
            *([J.issn_l.not_in(sorted(set(ignored)))] if ignored else []),
        )
        .subquery()
    )


def _topic_label_exists(topics: Any, topic: str) -> Any:
    """EXISTS a topics entry whose display_name equals `topic`
    case-insensitively; jsonb_array_elements in FROM is implicit LATERAL."""
    elems = func.jsonb_array_elements(func.coalesce(topics, text("'[]'::jsonb"))).table_valued(
        "value", name="t"
    )
    return exists(
        select(1)
        .select_from(elems)
        .where(func.lower(elems.c.value.op("->>")("display_name")) == topic.lower())
    )


def _publisher_agg(rows: Any, topics: list[str] | None) -> Any:
    """Per-publisher journal aggregates; active topic filters ride along as
    a bool_or column because they are per-journal predicates."""
    cols: list[Any] = [
        rows.c.publisher_name.label("name"),
        func.count().label("n_journals"),
        func.coalesce(func.sum(rows.c.works), 0).label("n_works"),
        func.count().filter(rows.c.deal_covered.is_(True)).label("deal_journals"),
    ]
    cols += [func.count().filter(rows.c.oa_type == t).label(t) for t in OA_TYPES]
    cols += [func.count().filter(rows.c.quartile == q).label(q.lower()) for q in QUARTILES]
    cols += [
        func.count().filter(rows.c.apc_any).label("apc_journals"),
        func.min(rows.c.apc_euro).label("eur_min"),
        func.max(rows.c.apc_euro).label("eur_max"),
    ]
    if topics:
        hits = [_topic_label_exists(rows.c.topics, t) for t in topics]
        cols.append(func.bool_or(or_(*hits)).label("topic_hit"))
    return (
        select(*cols)
        .where(rows.c.publisher_name.is_not(None), rows.c.publisher_name != "")
        .group_by(rows.c.publisher_name)
        .subquery()
    )


def _filter_conds(
    agg: Any,
    *,
    oa_types: list[str] | None,
    deal: str,
    quartiles: list[str] | None,
    topic: list[str] | None,
    sizes: list[str] | None,
    has_apc: bool | None,
    has_works: bool | None,
) -> dict[str, Any]:
    """One condition per active publisher-level dimension, keyed so a
    facet's counts can drop its own while keeping all others."""
    conds: dict[str, Any] = {}
    if oa_types:
        conds["oa_type"] = or_(*[agg.c[t] > 0 for t in oa_types])
    if deal == "covered":
        conds["deal"] = agg.c.deal_journals > 0
    elif deal == "none":
        conds["deal"] = agg.c.deal_journals == 0
    if quartiles:
        conds["quartile"] = or_(*[agg.c[q.lower()] > 0 for q in quartiles])
    if topic:
        conds["topic"] = agg.c.topic_hit.is_(True)
    if sizes:
        buckets = {
            "1": agg.c.n_journals == 1,
            "2-4": agg.c.n_journals.between(2, 4),
            "5-9": agg.c.n_journals.between(5, 9),
            "10+": agg.c.n_journals >= 10,
        }
        conds["size"] = or_(*[buckets[s] for s in sizes])
    if has_apc is not None:
        conds["has_apc"] = agg.c.apc_journals > 0 if has_apc else agg.c.apc_journals == 0
    if has_works is not None:
        conds["has_works"] = agg.c.n_works > 0 if has_works else agg.c.n_works == 0
    return conds


def _order(agg: Any, sort: str, q: str | None) -> tuple[Any, str]:
    """(order expression, natural direction)."""
    if sort == "name":
        return func.lower(agg.c.name), "asc"
    if sort == "journals":
        return agg.c.n_journals, "desc"
    if sort == "deals":
        return agg.c.deal_journals, "desc"
    if sort == "apc":
        return func.coalesce(agg.c.eur_max, 0), "desc"
    if sort == "relevance" and q and q.strip():
        tier = case((agg.c.name.ilike(f"{_like(q.strip())}%", escape="\\"), 1), else_=0)
        return tier, "desc"
    return agg.c.n_works, "desc"  # works, and relevance without q


async def _page_topics(
    session: AsyncSession, rows: Any, names: list[str], top: int
) -> dict[str, list[dict[str, Any]]]:
    """Works-weighted topic mass per publisher (harvest.authors.topic_mass),
    page-sized."""
    if not names:
        return {}
    journal_rows = (
        await session.execute(
            select(rows.c.issn_l, rows.c.publisher_name, rows.c.works, rows.c.topics).where(
                rows.c.publisher_name.in_(names)
            )
        )
    ).all()
    venues: dict[str, dict[str, int]] = {}
    topics_by_issn: dict[str, dict[str, list[Any]]] = {}
    for r in journal_rows:
        venues.setdefault(r.publisher_name, {})[r.issn_l] = r.works
        topics_by_issn.setdefault(r.publisher_name, {})[r.issn_l] = r.topics or []
    out: dict[str, list[dict[str, Any]]] = {}
    for name in names:
        mass = topic_mass(venues.get(name, {}), topics_by_issn.get(name, {}))
        out[name] = [
            {"name": n, "n": m}
            for n, m in sorted(mass.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
        ]
    return out


def _item(row: Any, topics: list[dict[str, Any]]) -> dict[str, Any]:
    q1, q2, q3, q4 = row.q1, row.q2, row.q3, row.q4
    return {
        "name": row.name,
        "n_journals": row.n_journals,
        "n_works": int(row.n_works or 0),
        "deal_journals": row.deal_journals,
        "oa_types": {t: getattr(row, t) for t in OA_TYPES},
        "quartiles": {
            "q1": q1,
            "q2": q2,
            "q3": q3,
            "q4": q4,
            "none": row.n_journals - (q1 + q2 + q3 + q4),
        },
        "apc": {
            "n_journals": row.apc_journals,
            "eur_min": float(row.eur_min) if row.eur_min is not None else None,
            "eur_max": float(row.eur_max) if row.eur_max is not None else None,
        },
        "topics": topics,
    }


async def _topic_facet(
    session: AsyncSession, rows: Any, agg: Any, conds: dict[str, Any], q_cond: Any
) -> dict[str, int]:
    """Publishers (under every filter except topic) with >=1 journal per
    topic label; top 10 by publisher count."""
    others = [c for key, c in conds.items() if key != "topic"]
    pubs = (
        select(agg.c.name)
        .where(*others, *([q_cond] if q_cond is not None else []))
        .subquery()
    )
    elems = func.jsonb_array_elements(
        func.coalesce(rows.c.topics, text("'[]'::jsonb"))
    ).table_valued("value", name="t")
    label = elems.c.value.op("->>")("display_name")
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message=".*cartesian product.*", category=sa_exc.SAWarning
        )
        pairs = (
            await session.execute(
                select(label.label("topic"), func.count(func.distinct(pubs.c.name)).label("n"))
                .select_from(pubs.join(rows, rows.c.publisher_name == pubs.c.name), elems)
                .where(label.is_not(None))
                .group_by(label)
                .order_by(text("2 DESC"), text("1"))
                .limit(TOPIC_FACET_LIMIT)
            )
        ).all()
    return {p.topic: int(p.n) for p in pairs}


async def _facets(
    session: AsyncSession, agg: Any, conds: dict[str, Any], q_cond: Any
) -> dict[str, dict[str, int]]:
    """Drop-own-dimension publisher counts per facet (topic is separate)."""

    async def _counts(conds_map: dict[str, Any], *flags: Any) -> list[int]:
        row = (
            await session.execute(
                select(func.count(), *[func.count().filter(f) for f in flags])
                .select_from(agg)
                .where(*conds_map.values(), *([q_cond] if q_cond is not None else []))
            )
        ).one()
        # Skip the leading COUNT(*); callers zip flags onto the rest.
        return [int(v or 0) for v in row[1:]]

    out: dict[str, dict[str, int]] = {}
    others = {k: c for k, c in conds.items() if k != "oa_type"}
    counts = await _counts(others, *[agg.c[t] > 0 for t in OA_TYPES])
    out["oa_type"] = dict(zip(OA_TYPES, counts, strict=True))
    others = {k: c for k, c in conds.items() if k != "deal"}
    covered, total = await _counts(others, agg.c.deal_journals > 0, agg.c.deal_journals == 0)
    out["deal"] = {"covered": covered, "none": total}
    others = {k: c for k, c in conds.items() if k != "quartile"}
    counts = await _counts(others, *[agg.c[q.lower()] > 0 for q in QUARTILES])
    out["quartile"] = dict(zip(QUARTILES, counts, strict=True))
    others = {k: c for k, c in conds.items() if k != "has_apc"}
    yes, no = await _counts(others, agg.c.apc_journals > 0, agg.c.apc_journals == 0)
    out["has_apc"] = {"yes": yes, "no": no}
    others = {k: c for k, c in conds.items() if k != "size"}
    counts = await _counts(
        others,
        agg.c.n_journals == 1,
        agg.c.n_journals.between(2, 4),
        agg.c.n_journals.between(5, 9),
        agg.c.n_journals >= 10,
    )
    out["size"] = dict(zip(SIZE_BUCKETS, counts, strict=True))
    return out


async def search_publishers(
    session: AsyncSession,
    *,
    institution_id: int,
    q: str | None = None,
    oa_types: list[str] | None = None,
    deal: str = "any",
    quartiles: list[str] | None = None,
    topic: list[str] | None = None,
    sizes: list[str] | None = None,
    has_apc: bool | None = None,
    has_works: bool | None = None,
    sort: str | None = None,
    dir: str | None = None,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
    include_facets: bool = True,
) -> dict[str, Any]:
    """Publisher roster for one institution: total is the filter match count,
    items the offset/limit page of the sorted matches (default sort
    relevance-with-q, else works desc)."""
    rows = _journal_rows(institution_id)
    agg = _publisher_agg(rows, topic)
    conds = _filter_conds(
        agg,
        oa_types=oa_types,
        deal=deal,
        quartiles=quartiles,
        topic=topic,
        sizes=sizes,
        has_apc=has_apc,
        has_works=has_works,
    )
    q_cond = agg.c.name.ilike(f"%{_like(q.strip())}%", escape="\\") if q and q.strip() else None
    where = list(conds.values()) + ([q_cond] if q_cond is not None else [])
    total = await session.scalar(select(func.count()).select_from(agg).where(*where)) or 0

    if sort is None:
        sort = "relevance" if q_cond is not None else "works"
    order_col, direction = _order(agg, sort, q)
    if dir in ("asc", "desc"):
        direction = dir
    head = order_col.desc() if direction == "desc" else order_col.asc()
    page_rows = (
        await session.execute(
            select(agg)
            .where(*where)
            .order_by(head, func.lower(agg.c.name), agg.c.name)
            .offset(offset)
            .limit(min(limit, MAX_LIMIT))
        )
    ).all()

    topics = await _page_topics(session, rows, [r.name for r in page_rows], TOPICS_PER_ITEM)
    items = [_item(r, topics.get(r.name, [])) for r in page_rows]
    facets: dict[str, dict[str, int]] = {}
    if include_facets:
        facets = await _facets(session, agg, conds, q_cond)
        facets["topic"] = await _topic_facet(session, rows, agg, conds, q_cond)
    return {"items": items, "total": int(total), "facets": facets}


async def publisher_detail(
    session: AsyncSession, institution: Institution, name: str
) -> dict[str, Any] | None:
    """Full publisher bundle; None = no browsable journal under this name
    (404 upstream). Deals reuse the journal-detail participation join."""
    iid = institution.id
    rows = _journal_rows(iid)
    issn_rows = (
        await session.execute(
            select(rows.c.issn_l).where(rows.c.publisher_name == name)
        )
    ).all()
    if not issn_rows:
        return None
    issns = [r.issn_l for r in issn_rows]

    agg = _publisher_agg(rows, None)
    row = (await session.execute(select(agg).where(agg.c.name == name))).one()
    topics = (await _page_topics(session, rows, [name], TOPICS_PER_DETAIL))[name]

    journals = await search_journals(
        session,
        institution_id=iid,
        publisher=name,
        sort="institution_works",
        limit=JOURNAL_CAP,
        include_facets=False,
    )

    # Same participation/override semantics as the journal detail deals.
    dj_scope = DealJournal.institution_id.is_not_distinct_from(
        case((DealInstitution.journal_override.is_(True), iid), else_=None)
    )
    deal_rows = (
        await session.execute(
            select(Deal, Publisher.name)
            .select_from(Deal)
            .join(
                DealInstitution,
                (DealInstitution.deal_id == Deal.id)
                & (DealInstitution.institution_id == iid),
            )
            .join(
                DealJournal,
                (DealJournal.deal_id == Deal.id)
                & dj_scope
                & DealJournal.excluded.is_not(True)
                & DealJournal.issn_l.in_(issns),
            )
            .outerjoin(Publisher, Publisher.id == Deal.publisher_id)
            .where(Deal.status == "current")
            .distinct()
            .order_by(Deal.id)
        )
    ).all()

    stats_rows = (
        await session.execute(
            select(InstitutionWorksStats)
            .where(
                InstitutionWorksStats.institution_id == iid,
                InstitutionWorksStats.issn_l.in_(issns),
                InstitutionWorksStats.year >= institution.data_window_start,
                InstitutionWorksStats.year <= (institution.data_window_end or 9999),
            )
            .order_by(InstitutionWorksStats.year)
        )
    ).scalars().all()
    by_source = {
        source: {s.year: s for s in stats_rows if s.source == source}
        for source in ("pure_canon", "openalex_institution_filter")
    }
    # Works count: Pure-canonical when present; OA split: always OpenAlex
    # (journal-detail convention).
    works_by_year = []
    for year in sorted({s.year for s in stats_rows}, reverse=True):
        oa_row = by_source["openalex_institution_filter"].get(year)
        primary = by_source["pure_canon"].get(year)
        if oa_row is None and primary is None:
            continue
        split = oa_row if oa_row is not None else primary
        works_by_year.append(
            {
                "year": year,
                "works_count": primary.works_count if primary is not None else split.works_count,
                "works_count_source": (
                    "pure_canon" if primary is not None else "openalex_institution_filter"
                ),
                "oa_gold": split.oa_gold,
                "oa_hybrid": split.oa_hybrid,
                "oa_green": split.oa_green,
                "oa_bronze": split.oa_bronze,
                "oa_diamond": split.oa_diamond,
                "oa_closed": split.oa_closed,
            }
        )

    return {
        "publisher": _item(row, topics),
        "journals": journals["items"],
        "deals": [(d, publisher_name) for d, publisher_name in deal_rows],
        "works_by_year": works_by_year,
    }
