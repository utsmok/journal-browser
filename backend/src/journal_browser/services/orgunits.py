"""Org-unit browsing: authors grouped by faculty, research_group, or
institute.

The author set mirrors the authors list gate (institutions.
require_confirmed_affiliation). Serving follows the publisher-directory
pattern: one cached per-institution snapshot of unit aggregates
(`_snapshot`, 24h TTL + harvest-epoch bump), then filter/sort/page/facets
in Python over the name-keyed rows; per-item topic distributions stay a
query-time GROUP BY for exactly the paged units. Unit membership is the
non-empty grouping column; works/APC/deal rollups bound to the
institution's data window. An explicit publication-year range recomputes
the works-derived columns (works, deal-covered works, authors with
in-range work) at query time — same edge population and author gates as
the snapshot, data window replaced by the clamped range — while the
roster and attribute columns stay snapshot."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Numeric, case, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..harvest.common import cache_epoch
from ..models import (
    ApcEvidence,
    Author,
    AuthorWork,
    Institution,
    Journal,
    JournalFlags,
    Work,
)
from .authorship import author_ids_openalex_only
from .cache import SNAPSHOT_CACHE, SNAPSHOT_TTL, cache_get, cache_put
from .search import _oa_type
from .works_query import (
    WORKS_STRATA,
    YEAR_BUCKETS,
    empty_year_buckets,
    strata_match,
    unit_author_join,
    unit_work_join,
    work_type_not_excluded,
    work_window,
    work_year_window,
)

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
JOURNAL_CAP = 15
AUTHOR_CAP = 50
#: OA statuses counting toward the top-authors diamond+gold share, and the
#: minimum counted works before an author is ranked by that share.
DIAMOND_GOLD = ("diamond", "gold")
AUTHOR_SHARE_MIN_WORKS = 4
DEAL_USAGE_CAP = 8
TOPICS_PER_ITEM = 3
TOPICS_PER_DETAIL = 5
SNAPSHOT_WORK_MEM = "256MB"  # cold-build-only, see _snapshot

LEVELS = ("faculty", "group", "institute")
SORT_KEYS = ("relevance", "name", "authors", "works", "deal_works")


@dataclass(slots=True)
class _Unit:
    """One unit row of the cached snapshot."""

    name: str
    faculty: str | None
    n_authors: int
    n_works: int
    n_groups: int | None
    deal_works: int
    apc_euro_total: float
    apc_n: int


def _unit_key(level: str) -> Any:
    # Institutes are their own unit level (MESA+ / TechMed / DSI), not a
    # faculty or a research group — the author's institute attribute.
    if level == "group":
        return Author.research_group
    return Author.institute if level == "institute" else Author.faculty


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
            work_type_not_excluded(Work.work_type),
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


async def _snapshot(session: AsyncSession, institution: Institution) -> dict[str, dict[str, _Unit]]:
    """Per-level unit aggregates for one institution, cached until the next
    harvest bump or 24h (publishers-snapshot pattern)."""
    cache_key = (
        institution.id,
        await cache_epoch(session),
    )
    hit = cache_get(SNAPSHOT_CACHE, cache_key, SNAPSHOT_TTL)
    if hit is not None:
        return hit
    snap: dict[str, dict[str, _Unit]] = {}
    # One-off build: keep the edge-join hash aggregates and sorts in
    # memory instead of spilling. SET LOCAL dies with the request's
    # transaction, so the pool is unaffected.
    await session.execute(text(f"SET LOCAL work_mem = '{SNAPSHOT_WORK_MEM}'"))
    for level in LEVELS:
        units = _unit_rows(institution, level)
        result = await session.execute(select(units))
        snap[level] = {
            r.name: _Unit(
                name=r.name,
                faculty=r.faculty,
                n_authors=int(r.n_authors),
                n_works=int(r.n_works or 0),
                n_groups=r.n_groups if level == "faculty" else None,
                deal_works=int(r.deal_works),
                apc_euro_total=float(r.apc_euro_total),
                apc_n=int(r.apc_n),
            )
            for r in result.all()
        }
    cache_put(SNAPSHOT_CACHE, cache_key, snap)
    return snap


def _scoped_unit_rows(institution: Institution, level: str, year_range: tuple[int, int]) -> Any:
    """Year-scoped works aggregates per unit: the snapshot's edge
    population (`_unit_rows`' `_edges` — same joins, author gates, and
    retired-at gate) with the data window replaced by the clamped
    publication-year range. Counts stay distinct-per-unit like the
    snapshot's deal rollup; the flags join is outer so journals without a
    flags row still fill n_works/n_authors."""
    iid = institution.id
    require_confirmed = institution.require_confirmed_affiliation
    key = _unit_key(level)
    edges = (
        select(
            key.label("name"),
            Work.pure_uuid.label("work_uuid"),
            Author.pure_uuid.label("author_uuid"),
            JournalFlags.deal_covered.label("deal_covered"),
        )
        .select_from(Author)
        .join(AuthorWork, unit_author_join(iid))
        .join(Work, unit_work_join(iid))
        .outerjoin(
            JournalFlags,
            (JournalFlags.institution_id == iid) & (JournalFlags.issn_l == Work.journal_issn_l),
        )
        .where(
            *_author_base(iid, require_confirmed),
            key.is_not(None),
            key != "",
            Work.retired_at.is_(None),
            *work_year_window(institution, year_range),
            work_type_not_excluded(Work.work_type),
        )
        .subquery()
    )
    return (
        select(
            edges.c.name.label("name"),
            func.count(func.distinct(edges.c.work_uuid)).label("n_works"),
            func.count(func.distinct(edges.c.work_uuid))
            .filter(edges.c.deal_covered.is_(True))
            .label("deal_works"),
            func.count(func.distinct(edges.c.author_uuid)).label("n_authors"),
        )
        .group_by(edges.c.name)
        .subquery()
    )


async def _scoped_units(
    session: AsyncSession,
    institution: Institution,
    level: str,
    year_range: tuple[int, int],
    units: dict[str, _Unit],
) -> dict[str, _Unit]:
    """The snapshot roster with the works-derived columns recomputed inside
    the clamped range; attribute columns (faculty, group count, APC
    rollups) keep the snapshot values and units without in-range works
    stay listed at zero (the authors-list convention)."""
    scoped = {
        r.name: r
        for r in (
            await session.execute(select(_scoped_unit_rows(institution, level, year_range)))
        ).all()
    }
    out: dict[str, _Unit] = {}
    for name, u in units.items():
        r = scoped.get(name)
        out[name] = _Unit(
            name=name,
            faculty=u.faculty,
            n_authors=int(r.n_authors) if r else 0,
            n_works=int(r.n_works) if r else 0,
            n_groups=u.n_groups,
            deal_works=int(r.deal_works) if r else 0,
            apc_euro_total=u.apc_euro_total,
            apc_n=u.apc_n,
        )
    return out


def _order_units(sort: str, q: str | None) -> tuple[Any, str]:
    """(sort key over _Unit rows, natural direction). SQL convention: head
    direction, ties broken by (lower(name), name) ascending."""

    def head(u: _Unit) -> Any:
        if sort == "name":
            return u.name.lower()
        if sort == "authors":
            return u.n_authors
        if sort == "deal_works":
            return u.deal_works
        if sort == "relevance" and q and q.strip():
            return 1 if u.name.lower().startswith(q.strip().lower()) else 0
        return u.n_works  # works, and relevance without q

    return head, "desc" if sort != "name" else "asc"


def _matches_q(u: _Unit, q: str) -> bool:
    """SQL ilike '%q%' twin: case-insensitive substring of the raw name
    (LIKE metacharacters stay literal, same as the escaped SQL path)."""
    return q.lower() in u.name.lower()


def _snapshot_facets(
    units: list[_Unit],
    level: str,
    wanted_faculty: set[str] | None,
    works: list[str] | None,
    uses_deals: bool | None,
) -> dict[str, dict[str, int]]:
    """Drop-own-dimension counts over the snapshot's pre-filtered rows
    (each facet re-applies every filter except its own; q already
    filtered the caller's copy)."""

    def _count(skip: str) -> list[_Unit]:
        rows = units
        if skip != "faculty" and wanted_faculty is not None:
            rows = [u for u in rows if (u.faculty or "").lower() in wanted_faculty]
        if skip != "works" and works:
            rows = [u for u in rows if strata_match(u.n_works, works)]
        if skip != "uses_deals" and uses_deals is True:
            rows = [u for u in rows if u.deal_works > 0]
        return rows

    facets: dict[str, dict[str, int]] = {}
    if level == "group":
        counts: dict[str, int] = {}
        for u in _count("faculty"):
            if u.faculty:
                counts[u.faculty] = counts.get(u.faculty, 0) + 1
        facets["faculty"] = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
    facets["size"] = {
        stratum: sum(1 for u in _count("works") if strata_match(u.n_works, [stratum]))
        for stratum in WORKS_STRATA
    }
    rows = _count("uses_deals")
    facets["uses_deals"] = {
        "yes": sum(1 for u in rows if u.deal_works > 0),
        "no": sum(1 for u in rows if u.deal_works == 0),
    }
    return facets


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
    dir: str | None = None,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
    include_facets: bool = True,
    year_range: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Unit roster for one institution: total is the filter match count,
    items the offset/limit page of the sorted matches (default sort
    relevance-with-q, else works desc). Serves from the cached unit
    snapshot; only the page's topic distributions hit the database.

    With an active publication-year range the works-derived columns
    (n_works, deal_works, n_authors = members with >=1 in-range work)
    come from `_scoped_units` instead of the snapshot, so the works
    strata filter, size/uses_deals facets, authors|works|deal_works sorts
    and total evaluate the scoped columns; the faculty facet and the
    attribute columns stay snapshot. Without a range nothing changes:
    byte-identical snapshot serving, cache untouched."""
    require_confirmed = institution.require_confirmed_affiliation
    snapshot = await _snapshot(session, institution)
    units = snapshot.get(level, {})
    if year_range is not None:
        units = await _scoped_units(session, institution, level, year_range, units)
    matches = list(units.values())

    wanted_faculty = {f.lower() for f in faculty} if faculty and level == "group" else None
    if wanted_faculty is not None:
        matches = [u for u in matches if (u.faculty or "").lower() in wanted_faculty]
    if works:
        matches = [u for u in matches if strata_match(u.n_works, works)]
    if uses_deals is True:
        matches = [u for u in matches if u.deal_works > 0]
    if q and q.strip():
        matches = [u for u in matches if _matches_q(u, q.strip())]
    total = len(matches)

    if sort is None:
        sort = "relevance" if q and q.strip() else "works"
    head, direction = _order_units(sort, q)
    # An explicit dir overrides the key's natural direction.
    if dir in ("asc", "desc"):
        direction = dir
    matches.sort(key=lambda u: (u.name.lower(), u.name))
    matches.sort(key=head, reverse=direction == "desc")
    page = matches[offset : offset + min(limit, MAX_LIMIT)]

    topics = await _unit_topics(
        session, institution.id, level, require_confirmed, [u.name for u in page], TOPICS_PER_ITEM
    )
    items = [_item(u, level, topics.get(u.name, [])) for u in page]

    facets: dict[str, dict[str, int]] = {}
    if include_facets:
        facets = _snapshot_facets(list(units.values()), level, wanted_faculty, works, uses_deals)
    return {"level": level, "items": items, "total": int(total), "facets": facets}


async def orgunit_detail(
    session: AsyncSession,
    institution: Institution,
    level: str,
    name: str,
    year_range: tuple[int, int] | None = None,
    sort: str = "share",
) -> dict[str, Any] | None:
    """Full unit bundle; None = unknown unit (404 upstream). An explicit
    publication-year range narrows the works-derived sections — the unit
    header (works/deal/authors counts via the _scoped_units merge), the
    venue works counts, the member authors' in-range works counts, the
    deal-usage work set and the CRIS-gap card (same scoping as the groups
    list); per-year rows (works_by_year) keep the data window, the unit's
    APC rollups stay snapshot, and the deal-usage euro follows the
    narrowed work set (journal attributes stay unfiltered). `sort` orders
    the member authors card: 'share' ranks by the diamond/gold OA share
    (default; authors below AUTHOR_SHARE_MIN_WORKS counted works rank
    last, share None), 'works' by works count; AUTHOR_CAP cuts after the
    chosen ordering."""
    iid = institution.id
    require_confirmed = institution.require_confirmed_affiliation
    unit = (await _snapshot(session, institution)).get(level, {}).get(name)
    if unit is None:
        return None
    if year_range is not None:
        # Works-derived header counts recomputed inside the range (the
        # list's merge, applied to the one unit); attribute columns and
        # the APC rollups stay snapshot.
        unit = (await _scoped_units(session, institution, level, year_range, {name: unit}))[name]

    topics_by_unit = await _unit_topics(
        session, iid, level, require_confirmed, [name], TOPICS_PER_DETAIL
    )
    # Units whose members all lack a primary topic have no query rows at
    # all, so the key is simply absent (KeyError was a 500).
    topics = topics_by_unit.get(name, [])

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
            year_range=year_range,
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
                *work_year_window(institution, year_range),
                work_type_not_excluded(Work.work_type),
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

    # Member rows: the denormalized n_works answers by default; an active
    # range recomputes it from the stored work edges (the authors-list
    # convention, same aggregation as search_authors' scoped subquery —
    # edge population, confirmed gate unchanged). The diamond/gold count
    # has no snapshot column, so it always comes from those same edges in
    # this one statement: inside the range when one is active, else from
    # the edge population the snapshot count mirrors exactly (edges to
    # retired or excluded-type works are never stored).
    dg_count = func.count().filter(Work.oa_status.in_(DIAMOND_GOLD)).label("dg")
    edge_counts = None
    if year_range is not None:
        lo, hi = year_range
        edge_counts = (
            select(
                AuthorWork.author_pure_uuid.label("author_pure_uuid"),
                func.count().label("n"),
                dg_count,
            )
            .select_from(AuthorWork)
            .join(Work, unit_work_join(iid))
            .where(
                AuthorWork.institution_id == iid,
                Work.year.between(lo, hi),
                work_type_not_excluded(Work.work_type),
            )
            .group_by(AuthorWork.author_pure_uuid)
            .subquery()
        )
    else:
        edge_counts = (
            select(
                AuthorWork.author_pure_uuid.label("author_pure_uuid"),
                dg_count,
            )
            .select_from(AuthorWork)
            .join(Work, unit_work_join(iid))
            .where(
                AuthorWork.institution_id == iid,
                work_type_not_excluded(Work.work_type),
            )
            .group_by(AuthorWork.author_pure_uuid)
            .subquery()
        )
    n_col = func.coalesce(edge_counts.c.n, 0) if year_range is not None else Author.n_works
    share = case(
        (
            n_col >= AUTHOR_SHARE_MIN_WORKS,
            cast(func.coalesce(edge_counts.c.dg, 0), Numeric) / n_col,
        ),
        else_=None,
    ).label("oa_diamond_gold_share")
    author_stmt = select(
        Author.pure_uuid,
        Author.name,
        n_col.label("n_works"),
        Author.orcid,
        Author.primary_topic,
        share,
    ).where(*membership)
    author_stmt = author_stmt.outerjoin(
        edge_counts, edge_counts.c.author_pure_uuid == Author.pure_uuid
    )
    # share: share desc (authors below the minimum rank last via the NULL
    # and the works tiebreakers); works: the previous works-desc ordering.
    # The cap applies after the chosen ordering, so the card's toggle
    # refetches with the other sort key.
    if sort == "works":
        author_order = (n_col.desc(), func.lower(Author.name), Author.pure_uuid)
    else:
        author_order = (
            share.desc().nulls_last(),
            n_col.desc(),
            func.lower(Author.name),
            Author.pure_uuid,
        )
    author_rows = (
        await session.execute(author_stmt.order_by(*author_order).limit(AUTHOR_CAP))
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
                work_type_not_excluded(Work.work_type),
            )
            .group_by(Work.year, Work.oa_status)
        )
    ).all()
    by_year: dict[int, dict[str, int]] = {}
    for row in year_rows:
        bucket = by_year.setdefault(
            row.year, {"year": row.year, "total": 0, **empty_year_buckets()}
        )
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
    # An active range narrows the work set (n_works and the euro sum both
    # describe the in-range works; the best-period evidence join itself is
    # unchanged).
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
            *work_year_window(institution, year_range),
            work_type_not_excluded(Work.work_type),
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

    # Member authors' resolved OpenAlex A-ids (uncapped, unlike
    # author_rows) drive the CRIS-gap query.
    aid_rows = (await session.execute(select(Author.openalex_ids).where(*membership))).all()
    member_aids = [aid for (ids,) in aid_rows for aid in (ids or [])]

    return {
        "unit": _item(unit, level, topics),
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
                "oa_diamond_gold_share": r.oa_diamond_gold_share,
            }
            for r in author_rows
        ],
        "works_by_year": works_by_year,
        "openalex_only": await author_ids_openalex_only(
            session, institution, member_aids, year_range
        ),
        "deal_usage": [
            {"label": r.label, "n_works": int(r.n_works), "euro": float(r.euro)} for r in usage_rows
        ],
    }
