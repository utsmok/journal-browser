"""Collaboration facets, overview trends, and funder/project credit rollups."""

from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import (
    and_,
    func,
    literal,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    Institution,
    Journal,
    PartnerInstitution,
    Work,
)
from ...queries import cache_epoch
from ...schemas import (
    CollaborationFunder,
    CollaborationProject,
    CollaborationTrendYear,
    FacetCount,
)
from ..cache import (
    FACET_CACHE,
    SNAPSHOT_TTL,
    cache_get,
    cache_put,
)
from ..collaborations_detail import (
    OA_OPEN_STATUSES,
)
from ..concurrency import together
from ..works_query import (
    YEAR_BUCKETS,
    unit_key,
    unit_work_conditions,
)
from .filters import (
    FACET_CAP,
    CollaborationFilters,
    _credit_name,
    _credit_sources_list,
    _credits,
    _home_country,
    _Payload,
    _payload,
    _primary_topic,
    _selected,
    _work_conditions,
)


def _facet_counts(rows: Sequence[Any], limit: int = FACET_CAP) -> list[FacetCount]:
    return [
        FacetCount(value=str(v), count=int(n))
        for v, n in sorted(rows, key=lambda r: (-int(r[1]), str(r[0])))
    ][:limit]


async def _partner_attribute_counts(
    session: AsyncSession, selected: Any, column: Any
) -> list[FacetCount]:
    stmt = (
        select(column.label("value"), func.count(func.distinct(selected.c.work)))
        .select_from(selected)
        .join(PartnerInstitution, PartnerInstitution.ror == selected.c.ror)
        .where(column.is_not(None))
        .group_by(column)
    )
    return _facet_counts((await session.execute(stmt)).all())


async def _facet_org_type(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
    deal_rors: frozenset[str],
) -> list[FacetCount]:
    return await _partner_attribute_counts(
        session,
        _selected(institution, filters, partner="org_type", deal_rors=deal_rors),
        func.coalesce(func.lower(PartnerInstitution.org_type), "unknown"),
    )


async def _facet_country(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
    deal_rors: frozenset[str],
) -> list[FacetCount]:
    return await _partner_attribute_counts(
        session,
        _selected(institution, filters, partner="country", deal_rors=deal_rors),
        func.upper(PartnerInstitution.country_code),
    )


async def _facet_source(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
    deal_rors: frozenset[str],
) -> list[FacetCount]:
    selected = _selected(institution, filters, link="source", deal_rors=deal_rors)
    rows = await session.execute(
        select(selected.c.source, func.count(func.distinct(selected.c.work))).group_by(
            selected.c.source
        )
    )
    return _facet_counts(rows.all())


async def _facet_oa_status(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
    deal_rors: frozenset[str],
) -> list[FacetCount]:
    selected = _selected(institution, filters, work="oa_status", deal_rors=deal_rors)
    rows = await session.execute(
        select(func.lower(Work.oa_status), func.count(func.distinct(selected.c.work)))
        .select_from(selected)
        .join(
            Work,
            and_(Work.institution_id == institution.id, Work.pure_uuid == selected.c.work),
        )
        .where(Work.oa_status.is_not(None))
        .group_by(func.lower(Work.oa_status))
    )
    return _facet_counts(rows.all())


async def _facet_topic(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
    deal_rors: frozenset[str],
) -> list[FacetCount]:
    selected = _selected(institution, filters, work="topic", deal_rors=deal_rors)
    topic = _primary_topic()
    rows = await session.execute(
        select(topic, func.count(func.distinct(selected.c.work)))
        .select_from(selected)
        .join(
            Work,
            and_(Work.institution_id == institution.id, Work.pure_uuid == selected.c.work),
        )
        .join(Journal, Journal.issn_l == Work.journal_issn_l)
        .where(topic.is_not(None), topic != "")
        .group_by(topic)
    )
    return _facet_counts(rows.all())


async def _facet_orgunit(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
    deal_rors: frozenset[str],
) -> list[FacetCount]:
    selected = _selected(institution, filters, work="orgunit", deal_rors=deal_rors)
    key = unit_key(filters.level)
    stmt = (
        select(key.label("value"), func.count(func.distinct(Work.pure_uuid)))
        .where(
            *_work_conditions(institution, filters, drop="orgunit"),
            *unit_work_conditions(institution, filters.level),
            Work.pure_uuid.in_(select(selected.c.work)),
            key.is_not(None),
            func.btrim(key) != "",
        )
        .group_by(key)
    )
    return _facet_counts((await session.execute(stmt)).all())


async def _credit_facet(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
    deal_rors: frozenset[str],
    dimension: str,
    jisc_map: dict[str, int],
) -> list[Any]:
    selected = _selected(institution, filters, work=dimension, deal_rors=deal_rors)
    works = (
        select(Work.pure_uuid.label("work"))
        .where(
            *_work_conditions(institution, filters, drop=dimension),
            Work.pure_uuid.in_(select(selected.c.work)),
        )
        .subquery()
    )
    credits = _credits(institution, dimension)
    stmt = (
        select(
            credits.c.key.label("key"),
            _credit_name(credits).label("name"),
            func.max(credits.c.code).label("code"),
            func.max(credits.c.acronym).label("acronym"),
            func.count(func.distinct(credits.c.work)).label("count"),
            _credit_sources_list(credits).label("sources"),
        )
        .where(credits.c.work.in_(select(works.c.work)), credits.c.key.is_not(None))
        .group_by(credits.c.key)
    )
    rows = (await session.execute(stmt)).all()
    ordered = sorted(rows, key=lambda r: (-int(r.count), r.name or "", r.key))[:FACET_CAP]
    if dimension == "funder":
        return [
            CollaborationFunder(
                key=r.key,
                name=r.name or r.key,
                sources=sorted(r.sources),
                works=int(r.count),
                jisc_funder_id=_jisc_id(r.key, jisc_map),
            )
            for r in ordered
        ]
    return [
        CollaborationProject(
            key=r.key,
            code=r.code,
            acronym=r.acronym,
            funder=r.name,
            source="openaire" if "openaire" in r.sources else "openalex",
            sources=sorted(r.sources),
            works=int(r.count),
        )
        for r in ordered
    ]


def _jisc_id(funder_key: str, jisc_map: dict[str, int]) -> int | None:
    if not funder_key.startswith("openalex:"):
        return None
    return jisc_map.get(funder_key.removeprefix("openalex:"))


async def _overview_trend(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
    selected: Any,
    home_cc: str | None,
) -> tuple[list[CollaborationTrendYear], int, int, int, int]:
    """Per-year totals + domestic/international + OA + organisation-type split
    over the filtered collaborative works, plus overall domestic/international/
    OA/closed totals."""
    total_by_year = dict(
        (
            await session.execute(
                select(Work.year, func.count())
                .where(*_work_conditions(institution, filters))
                .group_by(Work.year)
            )
        ).all()
    )
    # Collapse selected links to one row per collaborative work so domestic/
    # international and OA counts never double-count multi-partner works.
    if home_cc:
        is_dom = func.bool_or(func.upper(PartnerInstitution.country_code) == home_cc)
        is_intl = func.bool_or(
            and_(
                PartnerInstitution.country_code.is_not(None),
                func.upper(PartnerInstitution.country_code) != home_cc,
            )
        )
    else:
        is_dom = literal(False)
        is_intl = literal(True)

    per_work = (
        select(
            selected.c.work.label("work"),
            is_dom.label("has_domestic"),
            is_intl.label("has_intl"),
        )
        .select_from(selected)
        .join(PartnerInstitution, PartnerInstitution.ror == selected.c.ror)
        .group_by(selected.c.work)
        .subquery()
    )
    rows = (
        await session.execute(
            select(
                Work.year,
                func.count().label("with_partner"),
                func.count().filter(per_work.c.has_domestic).label("domestic"),
                func.count().filter(per_work.c.has_intl).label("international"),
                *(
                    func.count().filter(func.lower(Work.oa_status) == st).label(f"oa_{st}")
                    for st in YEAR_BUCKETS
                ),
            )
            .select_from(per_work)
            .join(
                Work, and_(Work.institution_id == institution.id, Work.pure_uuid == per_work.c.work)
            )
            .group_by(Work.year)
            .order_by(Work.year)
        )
    ).all()
    by_year = {int(r.year): r for r in rows}
    org_type = func.coalesce(func.lower(PartnerInstitution.org_type), "unknown")
    type_counts: dict[int, dict[str, int]] = defaultdict(dict)
    for yr, kind, count in await session.execute(
        select(Work.year, org_type, func.count(func.distinct(selected.c.work)))
        .select_from(selected)
        .join(PartnerInstitution, PartnerInstitution.ror == selected.c.ror)
        .join(Work, and_(Work.institution_id == institution.id, Work.pure_uuid == selected.c.work))
        .group_by(Work.year, org_type)
    ):
        type_counts[int(yr)][kind] = int(count)
    all_years = sorted({int(y) for y in total_by_year if y is not None} | set(by_year))
    trend: list[CollaborationTrendYear] = []
    domestic_total = 0
    intl_total = 0
    oa_total = 0
    closed_total = 0
    for yr in all_years:
        r = by_year.get(yr)
        if r is not None:
            dom = int(r.domestic)
            intl = int(r.international)
            domestic_total += dom
            intl_total += intl
            oa_vals = {f"oa_{st}": int(getattr(r, f"oa_{st}")) for st in YEAR_BUCKETS}
            oa_total += sum(oa_vals[f"oa_{st}"] for st in OA_OPEN_STATUSES)
            closed_total += oa_vals["oa_closed"]
            trend.append(
                CollaborationTrendYear(
                    year=yr,
                    total_works=int(total_by_year.get(yr, 0)),
                    with_partner=int(r.with_partner),
                    domestic=dom,
                    international=intl,
                    **oa_vals,
                    by_org_type=type_counts.get(yr, {}),
                )
            )
        else:
            trend.append(
                CollaborationTrendYear(
                    year=yr,
                    total_works=int(total_by_year.get(yr, 0)),
                    with_partner=0,
                    domestic=0,
                    international=0,
                )
            )
    return trend, domestic_total, intl_total, oa_total, closed_total


async def _summary(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
    *,
    include_facets: bool,
    deal_rors: frozenset[str],
    jisc_map: dict[str, int],
) -> dict[str, Any]:
    """Totals, overview trend and (when requested) facets, cached per epoch."""
    key = (
        "collab_summary_v3",
        institution.id,
        filters.q,
        *(
            tuple(v) if v else ()
            for v in (
                filters.org_types,
                filters.countries,
                filters.faculty,
                filters.funders,
                filters.projects,
                filters.sources,
                filters.oa_statuses,
                filters.topics,
            )
        ),
        filters.level,
        filters.size,
        filters.rollup,
        filters.lead,
        filters.min_works,
        filters.shares_deals,
        filters.year_range,
        include_facets,
        await cache_epoch(session),
    )
    hit = cache_get(FACET_CACHE, key, SNAPSHOT_TTL)
    if hit is not None:
        return hit
    selected = _selected(institution, filters, deal_rors=deal_rors)
    total_works, with_partner, total_partners = (
        await session.execute(
            select(
                select(func.count())
                .select_from(Work)
                .where(*_work_conditions(institution, filters))
                .scalar_subquery(),
                select(func.count(func.distinct(selected.c.work))).scalar_subquery(),
                select(func.count(func.distinct(selected.c.ror))).scalar_subquery(),
            )
        )
    ).one()
    by_source: dict[_Payload, int] = {"openalex": 0, "openaire": 0}
    for source, count in await session.execute(
        select(selected.c.source, func.count(func.distinct(selected.c.work))).group_by(
            selected.c.source
        )
    ):
        by_source[_payload(source)] = int(count)
    year_from, year_to = (
        await session.execute(
            select(func.min(Work.year), func.max(Work.year)).where(
                *_work_conditions(institution, filters)
            )
        )
    ).one()
    home_cc = await _home_country(session, institution)
    trend, domestic_works, international_works, oa_works, closed_works = await _overview_trend(
        session, institution, filters, selected, home_cc
    )

    facets_dict: dict[str, Any] | None = None
    if include_facets:
        facet_jobs: list[tuple[str, Callable[[AsyncSession], Awaitable[Any]]]] = [
            ("org_type", lambda own: _facet_org_type(own, institution, filters, deal_rors)),
            ("country", lambda own: _facet_country(own, institution, filters, deal_rors)),
            ("orgunit", lambda own: _facet_orgunit(own, institution, filters, deal_rors)),
            ("oa_status", lambda own: _facet_oa_status(own, institution, filters, deal_rors)),
            ("topic", lambda own: _facet_topic(own, institution, filters, deal_rors)),
            (
                "funder",
                lambda own: _credit_facet(own, institution, filters, deal_rors, "funder", jisc_map),
            ),
            (
                "project",
                lambda own: _credit_facet(
                    own, institution, filters, deal_rors, "project", jisc_map
                ),
            ),
            ("source", lambda own: _facet_source(own, institution, filters, deal_rors)),
        ]

        def wrap(name: str, fn: Callable[[AsyncSession], Awaitable[Any]]):
            async def run(own: AsyncSession) -> tuple[str, Any]:
                return name, await fn(own)

            return run

        facets_dict = dict(await together(session, [wrap(n, fn) for n, fn in facet_jobs]))

    summary: dict[str, Any] = {
        "total_works": int(total_works),
        "works_with_partner": int(with_partner),
        "total_partners": int(total_partners),
        "domestic_works": domestic_works,
        "international_works": international_works,
        "oa_works": oa_works,
        "closed_works": closed_works,
        "works_by_source": by_source,
        "year_from": year_from,
        "year_to": year_to,
        "trend": trend,
        "facets": facets_dict,
    }
    cache_put(FACET_CACHE, key, summary)
    return summary


# --- rows to response models ----------------------------------------------


@dataclass(slots=True)
class _Credits:
    funders: list[CollaborationFunder]
    projects: list[CollaborationProject]


async def _credit_lists(
    session: AsyncSession,
    institution: Institution,
    selected: Any,
    rors: Sequence[str] | None,
    cap: int,
    jisc_map: dict[str, int],
) -> dict[str, _Credits]:
    """Top `cap` funders and projects per partner. `rors` names the
    partners to fill. None fills every partner in `selected` that has a
    credit: the CSV export streams its partners later and looks each one
    up."""
    out: dict[str, _Credits] = {ror: _Credits([], []) for ror in rors or ()}
    if rors is not None and not rors:
        return out
    rows: dict[tuple[str, str], list[Any]] = defaultdict(list)

    def dimension_rows(dimension: str) -> Callable[[AsyncSession], Awaitable[Sequence[Any]]]:
        credits = _credits(institution, dimension)
        partners = [selected.c.ror.in_(list(rors))] if rors is not None else []
        stmt = (
            select(
                selected.c.ror.label("ror"),
                credits.c.key.label("key"),
                _credit_name(credits).label("name"),
                func.max(credits.c.code).label("code"),
                func.max(credits.c.acronym).label("acronym"),
                func.count(func.distinct(selected.c.work)).label("count"),
                _credit_sources_list(credits).label("sources"),
            )
            .select_from(selected)
            .join(credits, credits.c.work == selected.c.work)
            .where(*partners, credits.c.key.is_not(None))
            .group_by(selected.c.ror, credits.c.key)
        )

        async def run(own: AsyncSession) -> Sequence[Any]:
            return (await own.execute(stmt)).all()

        return run

    for dimension, found in zip(
        ("funder", "project"),
        await together(session, [dimension_rows("funder"), dimension_rows("project")]),
        strict=True,
    ):
        for row in found:
            rows[(row.ror, dimension)].append(row)
    for (ror, dimension), entries in rows.items():
        lists = out.setdefault(ror, _Credits([], []))
        entries.sort(key=lambda r: (-int(r.count), r.name or "", r.key))
        top = entries[:cap]
        if dimension == "funder":
            lists.funders = [
                CollaborationFunder(
                    key=e.key,
                    name=e.name or e.key,
                    sources=sorted(e.sources),
                    works=int(e.count),
                    jisc_funder_id=_jisc_id(e.key, jisc_map),
                )
                for e in top
            ]
        else:
            lists.projects = [
                CollaborationProject(
                    key=e.key,
                    code=e.code,
                    acronym=e.acronym,
                    funder=e.name,
                    source="openaire" if "openaire" in e.sources else "openalex",
                    sources=sorted(e.sources),
                    works=int(e.count),
                )
                for e in top
            ]
    return out
