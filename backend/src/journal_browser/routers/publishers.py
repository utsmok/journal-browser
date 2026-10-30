"""/api/v1/{code}/publishers: browsable journals aggregated per publisher."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BeforeValidator
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import InstitutionDep
from ..schemas import (
    DealDiscrepancyRow,
    DealOut,
    JournalListItem,
    PublisherDetailResponse,
    PublisherSearchResponse,
)
from ..services import publishers as publishers_service
from ..vocab import OaType

router = APIRouter(prefix="/publishers", tags=["publishers"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _split(raw: str | list | None) -> list[str] | None:
    # "|" not ",": publisher/topic values contain commas and spaces.
    # FastAPI hands list-typed params the assembled list of query values;
    # the frontend sends one pipe-joined key, repeated keys also work.
    if raw is None:
        return None
    if isinstance(raw, list):
        raw = "|".join(raw)
    values = [v for v in raw.split("|") if v]
    return values or None


#: Pipe-joined oa_type multi-select, validated against OaType (422).
OaTypeFilter = Annotated[list[OaType] | None, BeforeValidator(_split), Query(max_length=60)]
#: Pipe-joined quartile multi-select (422 on unknown values).
QuartileFilter = Annotated[
    list[Literal["Q1", "Q2", "Q3", "Q4"]] | None,
    BeforeValidator(_split),
    Query(max_length=20),
]


@router.get("", response_model=PublisherSearchResponse)
async def search_publishers(
    session: SessionDep,
    institution: InstitutionDep,
    q: Annotated[str | None, Query(max_length=200)] = None,
    oa_type: OaTypeFilter = None,
    deal: Annotated[str | None, Query(pattern="^(covered|none)$")] = None,
    quartile: QuartileFilter = None,
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
    # dimensions. Values validate at the boundary (422); size stays a
    # hand-checked bucket list.
    oa_types = list(oa_type) if oa_type else None
    quartiles = list(quartile) if quartile else None
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
        deal_discrepancies=[DealDiscrepancyRow(**row) for row in detail["deal_discrepancies"]],
        n_discrepancies=detail["n_discrepancies"],
        works_by_year=detail["works_by_year"],
    )
