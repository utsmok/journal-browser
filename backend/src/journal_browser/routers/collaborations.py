"""/api/v1/{code}/collaborations: partner institutions on joint works.

Counts come from work_partners, which the derive job builds from the
stored OpenAlex and OpenAIRE work payloads. Names, aliases, roll-ups and
coordinates come from partner_institutions (the ROR records).
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BeforeValidator
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import InstitutionDep
from ..schemas import (
    CollaborationDetailResponse,
    CollaborationMapResponse,
    CollaborationSearchResponse,
    CollaborationWorksResponse,
)
from ..services import collaborations as collaborations_service
from ..services.collaborations import CollaborationFilters
from ..services.works_query import clamped_year_range
from .params import split_multi, split_pipe

router = APIRouter(prefix="/collaborations", tags=["collaborations"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

DEFAULT_LIMIT = 25

YearFrom = Annotated[
    int | None,
    Query(
        ge=1900,
        le=2100,
        description="Publication-year range start (clamped to the institution's data window)",
    ),
]
YearTo = Annotated[
    int | None,
    Query(
        ge=1900,
        le=2100,
        description="Publication-year range end (clamped to the institution's data window)",
    ),
]


def collaboration_filters(
    institution: InstitutionDep,
    q: Annotated[str | None, Query(max_length=200)] = None,
    type: Annotated[
        list[str] | None,
        BeforeValidator(split_multi),
        Query(max_length=60, description="ROR organisation types (multi-select)"),
    ] = None,
    country: Annotated[
        list[str] | None,
        BeforeValidator(split_multi),
        Query(max_length=20, description="ISO 3166-1 alpha-2 country codes (multi-select)"),
    ] = None,
    level: Literal["faculty", "group", "institute"] = "faculty",
    faculty: Annotated[
        list[str] | None,
        BeforeValidator(split_pipe),
        Query(
            max_length=400,
            description="Org unit names at `level` (pipe-joined multi-select)",
        ),
    ] = None,
    funder: Annotated[
        list[str] | None,
        BeforeValidator(split_pipe),
        Query(max_length=400, description="Funder keys from the funder facet (pipe-joined)"),
    ] = None,
    project: Annotated[
        list[str] | None,
        BeforeValidator(split_pipe),
        Query(max_length=400, description="Project keys from the project facet (pipe-joined)"),
    ] = None,
    source: Annotated[
        list[Literal["openalex", "openaire"]] | None,
        BeforeValidator(split_pipe),
        Query(max_length=40, description="Payloads that supplied partner links (pipe-joined)"),
    ] = None,
    oa_status: Annotated[
        list[str] | None,
        BeforeValidator(split_multi),
        Query(max_length=60, description="Open access statuses (multi-select)"),
    ] = None,
    topic: Annotated[
        list[str] | None,
        BeforeValidator(split_pipe),
        Query(max_length=400, description="OpenAlex primary topics (pipe-joined)"),
    ] = None,
    size: Annotated[
        Literal["standard", "small", "all"],
        Query(
            description="Collaboration size: standard (<=20 partners, default), "
            "small (<=5 partners), or all (including mega-consortia)"
        ),
    ] = "standard",
    rollup: Annotated[
        bool,
        Query(
            description="Roll up inactive successors and same-city sub-units into their "
            "canonical organisation (default: true)"
        ),
    ] = True,
    lead: Annotated[
        Literal["all", "home", "partner"],
        Query(description="Corresponding-author lead filter: all, home, or partner"),
    ] = "all",
    min_works: Annotated[
        int | None,
        Query(ge=1, le=10000, description="Minimum shared works per partner"),
    ] = None,
    shares_deals: Annotated[
        bool | None,
        Query(description="Filter to partners sharing OA deals with the home institution"),
    ] = None,
    year_from: YearFrom = None,
    year_to: YearTo = None,
) -> CollaborationFilters:
    year_range = clamped_year_range(institution, year_from, year_to)
    return CollaborationFilters(
        q=q,
        org_types=type,
        countries=country,
        level=level,
        faculty=faculty,
        funders=funder,
        projects=project,
        sources=source,
        oa_statuses=oa_status,
        topics=topic,
        size=size,
        rollup=rollup,
        lead=lead,
        min_works=min_works,
        shares_deals=shares_deals,
        year_range=year_range,
    )


FiltersDep = Annotated[CollaborationFilters, Depends(collaboration_filters)]


@router.get("", response_model=CollaborationSearchResponse)
async def search_collaborations(
    session: SessionDep,
    institution: InstitutionDep,
    filters: FiltersDep,
    sort: Annotated[
        Literal["works", "name", "corresponding_works", "home_corresponding_works", "oa_share"],
        Query(description="Result sort key"),
    ] = "works",
    dir: Annotated[
        Literal["asc", "desc"] | None,
        Query(description="Sort direction; default desc for counts, asc for name"),
    ] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = DEFAULT_LIMIT,
    include_facets: bool = True,
    include_credits: bool = False,
) -> CollaborationSearchResponse:
    return await collaborations_service.search_collaborations(
        session,
        institution,
        filters,
        sort=sort,
        direction=dir,
        offset=offset,
        limit=limit,
        include_facets=include_facets,
        include_credits=include_credits,
    )


@router.get("/map", response_model=CollaborationMapResponse)
async def collaboration_map(
    session: SessionDep,
    institution: InstitutionDep,
    filters: FiltersDep,
) -> CollaborationMapResponse:
    return await collaborations_service.collaboration_map(session, institution, filters)


@router.get("/partners.csv")
async def collaborations_csv(
    session: SessionDep,
    institution: InstitutionDep,
    filters: FiltersDep,
) -> StreamingResponse:
    """The filtered partner list as CSV, without paging."""
    return await collaborations_service.collaborations_csv(session, institution, filters)


@router.get("/{ror}", response_model=CollaborationDetailResponse)
async def collaboration_detail(
    session: SessionDep,
    institution: InstitutionDep,
    filters: FiltersDep,
    ror: str,
    include_works: bool = True,
) -> CollaborationDetailResponse:
    detail = await collaborations_service.collaboration_detail(
        session, institution, ror, filters, include_works=include_works
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="partner not found")
    return detail


@router.get("/{ror}/works", response_model=CollaborationWorksResponse)
async def partner_works(
    session: SessionDep,
    institution: InstitutionDep,
    filters: FiltersDep,
    ror: str,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = DEFAULT_LIMIT,
) -> CollaborationWorksResponse:
    works = await collaborations_service.partner_works(
        session, institution, ror, filters, offset=offset, limit=limit
    )
    if works is None:
        raise HTTPException(status_code=404, detail="partner not found")
    return works


@router.get("/{ror}/works.csv")
async def partner_works_csv(
    session: SessionDep,
    institution: InstitutionDep,
    filters: FiltersDep,
    ror: str,
) -> StreamingResponse:
    """The joint works of one partner as CSV, without paging."""
    response = await collaborations_service.partner_works_csv(session, institution, ror, filters)
    if response is None:
        raise HTTPException(status_code=404, detail="partner not found")
    return response
