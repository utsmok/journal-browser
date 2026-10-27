"""/api/v1/{code}/publishers: browsable journals aggregated per publisher."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..routers.institutions import InstitutionDep
from ..schemas import (
    DealDiscrepancyRow,
    DealOut,
    JournalListItem,
    PublisherDetailResponse,
    PublisherSearchResponse,
)
from ..services import publishers as publishers_service
from ..services import search as search_service

router = APIRouter(prefix="/publishers", tags=["publishers"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _split(raw: str | None) -> list[str] | None:
    # "|" not ",": publisher/topic values contain commas and spaces
    values = [v for v in (raw or "").split("|") if v]
    return values or None


@router.get("", response_model=PublisherSearchResponse)
async def search_publishers(
    session: SessionDep,
    institution: InstitutionDep,
    q: Annotated[str | None, Query(max_length=200)] = None,
    oa_type: Annotated[str | None, Query(max_length=60)] = None,
    deal: Annotated[str | None, Query(pattern="^(covered|none)$")] = None,
    quartile: Annotated[str | None, Query(max_length=20)] = None,
    topic: Annotated[str | None, Query(max_length=100)] = None,
    size: Annotated[str | None, Query(max_length=20)] = None,
    has_apc: bool | None = None,
    has_works: bool | None = None,
    sort: Annotated[
        str | None, Query(pattern="^(relevance|name|journals|works|deals|apc)$")
    ] = None,
    dir: Annotated[str | None, Query(pattern="^(asc|desc)$")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = publishers_service.DEFAULT_LIMIT,
    include_facets: bool = True,
) -> PublisherSearchResponse:
    # Pipe-joined multi-selects, OR'd within a dimension, AND'd across
    # dimensions. Unknown vocabulary → 400 (the journals convention).
    oa_types = _split(oa_type)
    if unknown := [v for v in oa_types or [] if v not in search_service.OA_TYPES]:
        raise HTTPException(status_code=400, detail=f"unknown oa_type: {unknown}")
    quartiles = _split(quartile)
    if unknown := [v for v in quartiles or [] if v not in publishers_service.QUARTILES]:
        raise HTTPException(status_code=400, detail=f"unknown quartile: {unknown}")
    sizes = _split(size)
    if unknown := [v for v in sizes or [] if v not in publishers_service.SIZE_BUCKETS]:
        raise HTTPException(status_code=400, detail=f"unknown size: {unknown}")
    result = await publishers_service.search_publishers(
        session,
        institution_id=institution.id,
        q=q,
        oa_types=oa_types,
        deal=deal or "any",
        quartiles=quartiles,
        topic=_split(topic),
        sizes=sizes,
        has_apc=has_apc,
        has_works=has_works,
        sort=sort,
        dir=dir,
        offset=offset,
        limit=limit,
        include_facets=include_facets,
    )
    return PublisherSearchResponse(**result)


@router.get("/{name:path}", response_model=PublisherDetailResponse)
async def publisher_detail(
    name: str, session: SessionDep, institution: InstitutionDep
) -> PublisherDetailResponse:
    detail = await publishers_service.publisher_detail(session, institution, name)
    if detail is None:
        raise HTTPException(status_code=404, detail="publisher not found")
    return PublisherDetailResponse(
        publisher=detail["publisher"],
        journals=[JournalListItem(**item) for item in detail["journals"]],
        deals=[
            DealOut(
                **{f: getattr(d, f) for f in DealOut.model_fields if hasattr(d, f)},
                publisher_name=publisher_name,
                covers_in_group=n_covered,
            )
            for d, publisher_name, n_covered in detail["deals"]
        ],
        deal_discrepancies=[
            DealDiscrepancyRow(**row) for row in detail["deal_discrepancies"]
        ],
        n_discrepancies=detail["n_discrepancies"],
        works_by_year=detail["works_by_year"],
    )
