"""Collaboration partners: counts, facets, overview trends and detail for
/collaborations, plus compact partner summaries for org-unit and author pages.

work_partners holds one link per work and partner ROR id. The derive job
(harvest.work_partners) rebuilds it from stored OpenAlex and OpenAIRE work
payloads. partner_institutions holds the ROR records, searchable aliases,
and conservative parent/successor roll-up pointers (rollup_ror).

Every number here counts works, never raw links: a work with three partners
counts once in the totals and once under each of its partners. When rollup is
enabled (default), child/inactive RORs fold into their canonical partner and
links are deduplicated per (work, canonical partner) before any count runs.
"""

from collections.abc import AsyncIterator, Sequence
from typing import Any

from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...identifiers import normalize_ror
from ...models import Institution, PartnerInstitution, Work, WorkPartner
from ...queries import cache_epoch
from ...schemas import (
    CollaborationDetailResponse,
    CollaborationFacets,
    CollaborationLink,
    CollaborationMapPoint,
    CollaborationMapResponse,
    CollaborationPartner,
    CollaborationRelation,
    CollaborationSearchResponse,
    CollaborationWork,
    CollaborationWorkAuthor,
    CollaborationWorksResponse,
)
from ..cache import (
    FACET_CACHE,
    SNAPSHOT_TTL,
    SWR_CACHE,
    cache_get,
    cache_put,
    swr_get,
    swr_put,
    swr_schedule,
)
from ..collaborations_detail import (
    OA_OPEN_STATUSES,
    detail_breakdowns,
)
from ..collaborations_detail import (
    top_partners_for_author as top_partners_for_author,
)
from ..collaborations_detail import (
    top_partners_for_orgunit as top_partners_for_orgunit,
)
from ..concurrency import together
from ..csv_export import csv_cells, csv_response, csv_stream, safe_filename
from .facets import _credit_lists, _Credits, _summary
from .filters import (
    _ORG_TYPES,
    _PARTNER_CSV,
    _TREND_CSV,
    _WORK_CSV,
    AUTHOR_CAP,
    DETAIL_LIST_CAP,
    ITEM_LIST_CAP,
    RECENT_WORKS,
    CollaborationFilters,
    _jisc_funder_map,
    _joint_works,
    _link_conditions,
    _merged_counts,
    _ordered,
    _payload,
    _per_partner,
    _selected,
    _shared_deal_rors,
    _sources,
    _work_author_links,
    _work_conditions,
    _works_stmt,
)
from .filters import _valid_project_code as _valid_project_code

__all__ = [
    "CollaborationFilters",
    "collaboration_detail",
    "collaboration_map",
    "collaborations_csv",
    "collaborations_trend_csv",
    "partner_works",
    "partner_works_csv",
    "search_collaborations",
    "top_partners_for_author",
    "top_partners_for_orgunit",
]


def _partner(
    row: Any,
    total_works: int,
    credits: _Credits,
    *,
    deal_rors: frozenset[str],
    merged_counts: dict[str, int],
    rollup: bool,
) -> CollaborationPartner:
    works = int(row.works)
    oa_works = int(row.oa_works or 0)
    return CollaborationPartner(
        ror=row.ror,
        name=row.name,
        org_type=row.org_type,
        country_code=row.country_code,
        city=row.city,
        lat=None if row.lat is None else float(row.lat),
        lng=None if row.lng is None else float(row.lng),
        parent_ror=row.parent_ror,
        parent_name=row.parent_name,
        in_ror=bool(row.in_ror),
        works=works,
        share=round(works / total_works, 4) if total_works else None,
        corresponding_works=int(row.corresponding_works),
        home_corresponding_works=int(row.home_corresponding_works or 0),
        authorships=int(row.authorships or 0),
        oa_works=oa_works,
        closed_works=int(row.closed_works or 0),
        oa_share=round(oa_works / works, 4) if works else None,
        shares_deals=row.ror in deal_rors,
        merged_count=merged_counts.get(row.ror, 0) if rollup else 0,
        sources=_sources(row.sources),
        funders=credits.funders,
        projects=credits.projects,
    )


def _work(row: Any, author_links: list[CollaborationWorkAuthor] | None = None) -> CollaborationWork:
    return CollaborationWork(
        pure_uuid=row.pure_uuid,
        title=row.title or "",
        year=int(row.year),
        doi=row.doi_normalized,
        work_type=row.work_type,
        corresponding=bool(row.corresponding),
        home_corresponding=bool(row.home_corresponding),
        oa_status=row.oa_status,
        journal_issn_l=row.journal_issn_l,
        journal_title=row.journal_title,
        deal_covered=bool(row.deal_covered),
        source=_payload(row.source),
        authors=[a for a in (row.authors or "").split(", ") if a][:AUTHOR_CAP],
        author_links=author_links or [],
    )


async def _ror_details(
    session: AsyncSession, institution: Institution, record: PartnerInstitution | None
) -> dict[str, Any]:
    payload: dict[str, Any] = record.payload if record and isinstance(record.payload, dict) else {}
    names = sorted(
        payload.get("names") or [],
        key=lambda name: "ror_display" not in (name.get("types") or []),
    )
    labels: list[str] = []
    for name in names:
        value = str(name.get("value") or "").strip()
        if value and value not in labels:
            labels.append(value)
    links = [
        CollaborationLink(type=str(link.get("type") or ""), value=str(link.get("value") or ""))
        for link in payload.get("links") or []
        if link.get("type") and link.get("value")
    ]
    raw_rels = [
        (str(rel.get("type") or ""), r, str(rel.get("label") or ""))
        for rel in payload.get("relationships") or []
        if (r := normalize_ror(rel.get("id"))) is not None
    ][:20]
    rel_rors = [r for _, r, _ in raw_rels]
    linked_rel_rors: set[str] = set()
    if rel_rors:
        linked_rel_rors = set(
            (
                await session.execute(
                    select(WorkPartner.partner_ror)
                    .distinct()
                    .where(
                        WorkPartner.institution_id == institution.id,
                        WorkPartner.partner_ror.in_(rel_rors),
                    )
                )
            ).scalars()
        )
    relationships = [
        CollaborationRelation(type=t, ror=r, label=lbl, is_partner=r in linked_rel_rors)
        for t, r, lbl in raw_rels
    ]
    return {
        "status": record.status if record else None,
        "openalex_id": record.openalex_id if record else None,
        "labels": labels[:12],
        "links": links[:20],
        "relationships": relationships,
    }


def _file_stem(institution: Institution, *parts: str) -> str:
    return safe_filename("-".join(p for p in (institution.code, *parts) if p))


async def _csv_lines(rows: Sequence[Sequence[Any]]) -> AsyncIterator[list[str]]:
    for row in rows:
        yield csv_cells(row)


async def _linked(session: AsyncSession, institution: Institution, ror: str) -> bool:
    """True when the institution has any direct or rolled-up link to `ror`."""
    direct = await session.scalar(
        select(WorkPartner.work_pure_uuid)
        .where(
            WorkPartner.institution_id == institution.id,
            WorkPartner.partner_ror == ror,
        )
        .limit(1)
    )
    if direct is not None:
        return True
    rolled = await session.scalar(
        select(WorkPartner.work_pure_uuid)
        .join(PartnerInstitution, PartnerInstitution.ror == WorkPartner.partner_ror)
        .where(
            WorkPartner.institution_id == institution.id,
            PartnerInstitution.rollup_ror == ror,
        )
        .limit(1)
    )
    return rolled is not None


async def search_collaborations(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
    *,
    sort: str,
    direction: str | None,
    offset: int,
    limit: int,
    include_facets: bool,
    include_credits: bool = False,
) -> CollaborationSearchResponse:
    deal_rors = await _shared_deal_rors(session, institution)
    merged_counts = await _merged_counts(session) if filters.rollup else {}
    jisc_map = await _jisc_funder_map(session) if (include_facets or include_credits) else {}
    selected = _selected(institution, filters, deal_rors=deal_rors)
    summary = await _summary(
        session,
        institution,
        filters,
        include_facets=include_facets,
        deal_rors=deal_rors,
        jisc_map=jisc_map,
    )
    rows = (
        await session.execute(
            _ordered(_per_partner(institution, selected), sort, direction, filters.q)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    if include_credits and rows:
        credits = await _credit_lists(
            session, institution, selected, [r.ror for r in rows], ITEM_LIST_CAP, jisc_map
        )
    else:
        credits = {r.ror: _Credits([], []) for r in rows}
    return CollaborationSearchResponse(
        items=[
            _partner(
                r,
                summary["total_works"],
                credits[r.ror],
                deal_rors=deal_rors,
                merged_counts=merged_counts,
                rollup=filters.rollup,
            )
            for r in rows
        ],
        total_partners=summary["total_partners"],
        total_works=summary["total_works"],
        works_with_partner=summary["works_with_partner"],
        domestic_works=summary["domestic_works"],
        international_works=summary["international_works"],
        oa_works=summary["oa_works"],
        closed_works=summary["closed_works"],
        works_by_source=summary["works_by_source"],
        year_from=summary["year_from"],
        year_to=summary["year_to"],
        trend=summary["trend"],
        facets=CollaborationFacets(**summary["facets"]) if summary["facets"] is not None else None,
    )


async def collaboration_map(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
) -> Response:
    """The filtered partners that have coordinates, as JSON text built
    once per filters and harvest epoch and cached like the search summary.
    A cold call aggregates every partner; a warm one returns the stored
    text, which also skips validating about 9,000 rows per request."""
    epoch = await cache_epoch(session)
    key = ("collab_map", institution.id, *_collab_filters_key(filters), epoch)
    body = cache_get(FACET_CACHE, key, SNAPSHOT_TTL)
    if body is None:
        deal_rors = await _shared_deal_rors(session, institution)
        body = await _map_body(session, institution, filters, deal_rors)
        cache_put(FACET_CACHE, key, body)
    return Response(content=body, media_type="application/json")


async def _map_body(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
    deal_rors: frozenset[str],
) -> str:
    per_partner = _per_partner(
        institution, _selected(institution, filters, deal_rors=deal_rors)
    ).subquery()
    rows = (
        await session.execute(
            select(
                per_partner.c.ror,
                per_partner.c.name,
                per_partner.c.country_code,
                per_partner.c.city,
                per_partner.c.org_type,
                per_partner.c.lat,
                per_partner.c.lng,
                per_partner.c.works,
                per_partner.c.corresponding_works,
                per_partner.c.home_corresponding_works,
                per_partner.c.oa_works,
            )
        )
    ).all()
    items = [_map_row(r) for r in rows if r.lat is not None and r.lng is not None]
    return CollaborationMapResponse(items=items, unmapped=len(rows) - len(items)).model_dump_json()


def _map_row(r: Any) -> CollaborationMapPoint:
    works = int(r.works)
    oa_works = int(r.oa_works or 0)
    return (
        r.ror,
        r.name,
        r.country_code,
        r.city,
        (r.org_type or "unknown").lower(),
        float(r.lat),
        float(r.lng),
        works,
        int(r.corresponding_works),
        int(r.home_corresponding_works or 0),
        round(oa_works / works, 4) if works else None,
    )


def _collab_filters_key(filters: CollaborationFilters) -> tuple[Any, ...]:
    return (
        filters.q,
        tuple(filters.org_types or ()),
        tuple(filters.countries or ()),
        filters.level,
        tuple(filters.faculty or ()),
        tuple(filters.funders or ()),
        tuple(filters.projects or ()),
        tuple(filters.sources or ()),
        tuple(filters.oa_statuses or ()),
        tuple(filters.topics or ()),
        filters.size,
        filters.rollup,
        filters.lead,
        filters.min_works,
        filters.shares_deals,
        filters.year_range,
    )


async def collaboration_detail(
    session: AsyncSession,
    institution: Institution,
    ror: str,
    filters: CollaborationFilters,
    *,
    include_works: bool = True,
) -> CollaborationDetailResponse | None:
    swr_key = ("collab_detail", institution.id, ror, _collab_filters_key(filters), include_works)
    epoch = await cache_epoch(session)
    fresh, bundle = swr_get(SWR_CACHE, swr_key, epoch)
    if fresh:
        return bundle
    if bundle is not None:
        swr_schedule(
            SWR_CACHE,
            swr_key,
            _collab_detail_factory(institution.id, ror, filters, include_works),
        )
        return bundle
    epoch, built = await _build_collaboration_detail(
        session, institution, ror, filters, include_works=include_works
    )
    if built is None:
        return None
    swr_put(SWR_CACHE, swr_key, epoch, built)
    return built


def _collab_detail_factory(iid: int, ror: str, filters: CollaborationFilters, include_works: bool):
    async def _factory():
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from ...db import get_engine

        async with async_sessionmaker(get_engine(), expire_on_commit=False)() as session:
            inst = (await session.scalars(select(Institution).where(Institution.id == iid))).one()
            return await _build_collaboration_detail(
                session, inst, ror, filters, include_works=include_works
            )

    return _factory


async def _build_collaboration_detail(
    session: AsyncSession,
    institution: Institution,
    ror: str,
    filters: CollaborationFilters,
    *,
    include_works: bool = True,
) -> tuple[Any, CollaborationDetailResponse | None]:
    if not await _linked(session, institution, ror):
        return await cache_epoch(session), None
    deal_rors = await _shared_deal_rors(session, institution)
    merged_counts = await _merged_counts(session) if filters.rollup else {}
    jisc_map = await _jisc_funder_map(session)
    selected = _selected(institution, filters, deal_rors=deal_rors)
    row = (
        await session.execute(_per_partner(institution, selected).where(selected.c.ror == ror))
    ).one_or_none()
    total_works = int(
        (
            await session.scalar(
                select(func.count())
                .select_from(Work)
                .where(*_work_conditions(institution, filters))
            )
        )
        or 0
    )
    if row is not None:
        credits = (
            await _credit_lists(session, institution, selected, [ror], DETAIL_LIST_CAP, jisc_map)
        )[ror]
        base = _partner(
            row,
            total_works,
            credits,
            deal_rors=deal_rors,
            merged_counts=merged_counts,
            rollup=filters.rollup,
        )
    else:
        record_stub = await session.get(PartnerInstitution, ror)
        base = CollaborationPartner(
            ror=ror,
            name=record_stub.name if record_stub and record_stub.name else ror,
            org_type=record_stub.org_type if record_stub else None,
            country_code=record_stub.country_code if record_stub else None,
            city=record_stub.city if record_stub else None,
            lat=float(record_stub.lat) if record_stub and record_stub.lat is not None else None,
            lng=float(record_stub.lng) if record_stub and record_stub.lng is not None else None,
            parent_ror=record_stub.parent_ror if record_stub else None,
            parent_name=record_stub.parent_name if record_stub else None,
            in_ror=record_stub is not None and record_stub.payload is not None,
            works=0,
            corresponding_works=0,
            home_corresponding_works=0,
            authorships=0,
            oa_works=0,
            closed_works=0,
            oa_share=None,
            shares_deals=ror in deal_rors,
            merged_count=merged_counts.get(ror, 0) if filters.rollup else 0,
            sources=[],
            funders=[],
            projects=[],
        )

    joint = _joint_works(institution, filters, ror, deal_rors=deal_rors)
    breakdowns = await detail_breakdowns(
        session,
        institution,
        ror,
        joint,
        rollup=filters.rollup,
        work_conds=_work_conditions(institution, filters),
        link_conds=_link_conditions(filters),
        together=together,
    )

    recent_items: list[CollaborationWork] = []
    if include_works:
        recent_rows = (
            await session.execute(_works_stmt(institution, joint).limit(RECENT_WORKS))
        ).all()
        author_links = await _work_author_links(
            session, institution, [r.pure_uuid for r in recent_rows]
        )
        recent_items = [_work(r, author_links.get(r.pure_uuid)) for r in recent_rows]

    record = await session.get(PartnerInstitution, ror)
    details = await _ror_details(session, institution, record)
    return await cache_epoch(session), CollaborationDetailResponse(
        **base.model_dump(),
        **details,
        **breakdowns,
        total_works=total_works,
        recent_works=recent_items,
    )


async def partner_works(
    session: AsyncSession,
    institution: Institution,
    ror: str,
    filters: CollaborationFilters,
    *,
    offset: int,
    limit: int,
) -> CollaborationWorksResponse | None:
    if not await _linked(session, institution, ror):
        return None
    deal_rors = await _shared_deal_rors(session, institution)
    joint = _joint_works(institution, filters, ror, deal_rors=deal_rors)
    total = await session.scalar(select(func.count()).select_from(joint))
    rows = (
        await session.execute(_works_stmt(institution, joint).offset(offset).limit(limit))
    ).all()
    author_links = await _work_author_links(session, institution, [r.pure_uuid for r in rows])
    return CollaborationWorksResponse(
        items=[_work(r, author_links.get(r.pure_uuid)) for r in rows],
        total=int(total or 0),
    )


async def collaborations_csv(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
) -> StreamingResponse:
    deal_rors = await _shared_deal_rors(session, institution)
    jisc_map = await _jisc_funder_map(session)
    selected = _selected(institution, filters, deal_rors=deal_rors)
    total_works = await session.scalar(
        select(func.count()).select_from(Work).where(*_work_conditions(institution, filters))
    )
    # Credits come from their own aggregate queries: once for every
    # partner, not once per streamed partition.
    credits = await _credit_lists(session, institution, selected, None, ITEM_LIST_CAP, jisc_map)
    no_credits = _Credits([], [])
    lines = await csv_stream(
        session,
        _ordered(_per_partner(institution, selected), "works", None, filters.q),
        lambda row: _partner_csv_row(row, credits.get(row.ror, no_credits), deal_rors, total_works),
    )
    return csv_response(
        f"{_file_stem(institution, 'collaborations-partners')}.csv", lines, _PARTNER_CSV
    )


def _partner_csv_row(
    row: Any, credits: _Credits, deal_rors: frozenset[str], total_works: int | None
) -> list[Any]:
    works = int(row.works)
    oa_works = int(row.oa_works or 0)
    return [
        row.ror,
        row.name,
        row.org_type,
        row.country_code,
        row.city,
        works,
        int(row.home_corresponding_works or 0),
        int(row.corresponding_works),
        int(row.authorships or 0),
        oa_works,
        int(row.closed_works or 0),
        round(oa_works / works, 4) if works else None,
        "yes" if row.ror in deal_rors else "no",
        round(works / total_works, 4) if total_works else None,
        " ".join(sorted(row.sources or [])),
        "; ".join(f.name for f in credits.funders),
        "; ".join(p.acronym or p.code or p.funder or p.key for p in credits.projects),
    ]


async def collaborations_trend_csv(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
) -> StreamingResponse:
    """One row per publication year: all works, collaborative works and their
    domestic, open access and organisation-type split. Each `<type>_share` is
    the share of that year's collaborative works with a partner of that type."""
    summary = await _summary(
        session,
        institution,
        filters,
        include_facets=False,
        deal_rors=await _shared_deal_rors(session, institution),
        jisc_map={},
    )

    def share(part: int, whole: int) -> float | None:
        return round(part / whole, 4) if whole else None

    table: list[list[Any]] = []
    for y in summary["trend"]:
        row: list[Any] = [
            y.year,
            y.total_works,
            y.with_partner,
            share(y.with_partner, y.total_works),
            y.domestic,
            y.international,
            sum(getattr(y, f"oa_{st}") for st in OA_OPEN_STATUSES),
            y.oa_closed,
        ]
        for kind in _ORG_TYPES:
            count = y.by_org_type.get(kind, 0)
            row += [count, share(count, y.with_partner)]
        table.append(row)
    return csv_response(
        f"{_file_stem(institution, 'collaborations-trend')}.csv",
        _csv_lines(table),
        _TREND_CSV,
    )


async def partner_works_csv(
    session: AsyncSession,
    institution: Institution,
    ror: str,
    filters: CollaborationFilters,
) -> StreamingResponse | None:
    if not await _linked(session, institution, ror):
        return None
    deal_rors = await _shared_deal_rors(session, institution)
    joint = _joint_works(institution, filters, ror, deal_rors=deal_rors)
    lines = await csv_stream(session, _works_stmt(institution, joint), _work_csv_row)
    return csv_response(
        f"{_file_stem(institution, 'collaborations', ror, 'works')}.csv", lines, _WORK_CSV
    )


def _work_csv_row(r: Any) -> list[Any]:
    return [
        r.pure_uuid,
        r.title,
        r.year,
        r.doi_normalized,
        r.work_type,
        r.journal_title,
        r.oa_status,
        "yes" if r.deal_covered else "no",
        "yes" if r.home_corresponding else "no",
        "yes" if r.corresponding else "no",
        r.source,
        r.authors,
    ]
