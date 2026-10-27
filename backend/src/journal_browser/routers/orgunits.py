"""/api/v1/{code}/orgunits: faculties and research groups (author unions)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..routers.institutions import InstitutionDep
from ..schemas import OrgUnitDetailResponse, OrgUnitSearchResponse
from ..services import orgunits as orgunits_service

router = APIRouter(prefix="/orgunits", tags=["orgunits"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _split(raw: str | None) -> list[str] | None:
    # "|" not ",": faculty/group values contain commas and spaces
    values = [v for v in (raw or "").split("|") if v]
    return values or None


@router.get("", response_model=OrgUnitSearchResponse)
async def search_orgunits(
    session: SessionDep,
    institution: InstitutionDep,
    level: Literal["faculty", "group"] = "faculty",
    q: Annotated[str | None, Query(max_length=200)] = None,
    faculty: Annotated[str | None, Query(max_length=200)] = None,
    works: Annotated[str | None, Query(max_length=60)] = None,
    uses_deals: bool | None = None,
    sort: Annotated[
        str | None, Query(pattern="^(relevance|name|authors|works|deal_works)$")
    ] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = orgunits_service.DEFAULT_LIMIT,
    include_facets: bool = True,
) -> OrgUnitSearchResponse:
    # Pipe-joined multi-selects, OR'd within a dimension, AND'd across
    # dimensions; unknown strata match nothing (the authors convention).
    return OrgUnitSearchResponse(
        **await orgunits_service.search_orgunits(
            session,
            institution=institution,
            level=level,
            q=q,
            faculty=_split(faculty),
            works=_split(works),
            uses_deals=uses_deals,
            sort=sort,
            offset=offset,
            limit=limit,
            include_facets=include_facets,
        )
    )


@router.get("/faculty/{name:path}", response_model=OrgUnitDetailResponse)
async def faculty_detail(
    name: str, session: SessionDep, institution: InstitutionDep
) -> OrgUnitDetailResponse:
    detail = await orgunits_service.orgunit_detail(session, institution, "faculty", name)
    if detail is None:
        raise HTTPException(status_code=404, detail="orgunit not found")
    return OrgUnitDetailResponse(**detail)


@router.get("/group/{name:path}", response_model=OrgUnitDetailResponse)
async def group_detail(
    name: str, session: SessionDep, institution: InstitutionDep
) -> OrgUnitDetailResponse:
    detail = await orgunits_service.orgunit_detail(session, institution, "group", name)
    if detail is None:
        raise HTTPException(status_code=404, detail="orgunit not found")
    return OrgUnitDetailResponse(**detail)
