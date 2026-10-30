"""/api/v1/institutions: hosted-institution directory."""

from fastapi import APIRouter
from pydantic import BaseModel

from ..deps import SessionDep
from ..harvest.common import get_active_institutions

router = APIRouter(prefix="/institutions", tags=["institutions"])


class InstitutionOut(BaseModel):
    code: str
    name: str
    short_name: str | None = None
    data_window_start: int
    data_window_end: int | None = None
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
