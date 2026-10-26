"""/api/v1/institutions: hosted-institution directory, plus the shared
path-scope dependency every /{code}/... router resolves through."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..harvest.common import get_active_institutions, get_institution_by_code
from ..models import Institution

router = APIRouter(prefix="/institutions", tags=["institutions"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class InstitutionOut(BaseModel):
    code: str
    name: str
    short_name: str | None = None
    is_default: bool
    data_window_start: int
    data_window_end: int = 0  # 0 = open
    library_url: str | None = None
    oa_guide_url: str | None = None
    support_email: str | None = None
    admin_contact: str | None = None
    research_portal_url: str | None = None


@router.get("", response_model=list[InstitutionOut])
async def list_institutions(session: SessionDep) -> list[InstitutionOut]:
    return [
        InstitutionOut(
            code=inst.code or "",
            name=inst.name,
            short_name=inst.short_name,
            is_default=inst.is_default,
            data_window_start=inst.data_window_start,
            data_window_end=inst.data_window_end,
            library_url=inst.library_url,
            oa_guide_url=inst.oa_guide_url,
            support_email=inst.support_email,
            admin_contact=inst.admin_contact,
            research_portal_url=inst.research_portal_url,
        )
        for inst in await get_active_institutions(session)
    ]


async def get_scoped_institution(
    institution_code: str, session: SessionDep
) -> Institution:
    """Resolve /{institution_code}/... path scopes; 404 for unknown codes."""
    inst = await get_institution_by_code(session, institution_code)
    if inst is None:
        raise HTTPException(status_code=404, detail=f"unknown institution: {institution_code}")
    return inst


InstitutionDep = Annotated[Institution, Depends(get_scoped_institution)]
