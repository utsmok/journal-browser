"""Shared FastAPI dependencies: DB session and /{code}/... institution scope."""

from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .harvest.common import get_institution_by_code
from .models import Institution

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_scoped_institution(institution_code: str, session: SessionDep) -> Institution:
    """Resolve /{institution_code}/... path scopes; 404 for unknown codes."""
    inst = await get_institution_by_code(session, institution_code)
    if inst is None:
        raise HTTPException(status_code=404, detail=f"unknown institution: {institution_code}")
    return inst


InstitutionDep = Annotated[Institution, Depends(get_scoped_institution)]
