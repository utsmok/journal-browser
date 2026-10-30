"""Public feedback intake: POST /api/v1/feedback from the in-app widget.

Anonymous by design — the site has no user accounts. The payload carries a
frontend dump of the TanStack Query cache (page_data), so data reports arrive
with the exact API responses the reporter saw. Listing and triage live in the
admin router.
"""

import json
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Feedback
from ..vocab import FeedbackCategory

router = APIRouter(prefix="/feedback", tags=["feedback"])

MAX_PAGE_DATA_BYTES = 1_000_000

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class CreateFeedbackIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=8000)
    category: FeedbackCategory | None = None
    page_url: str | None = Field(default=None, max_length=2048)
    page_data: dict[str, Any] = Field(default_factory=dict)


class FeedbackOut(BaseModel):
    id: int
    title: str
    status: str
    created_at: datetime


@router.post("", status_code=201)
async def create_feedback(body: CreateFeedbackIn, session: SessionDep) -> FeedbackOut:
    if len(json.dumps(body.page_data)) > MAX_PAGE_DATA_BYTES:
        raise HTTPException(413, "page_data too large")

    row = Feedback(
        title=body.title.strip(),
        description=body.description.strip(),
        category=body.category,
        page_url=body.page_url,
        page_data=body.page_data,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return FeedbackOut(id=row.id, title=row.title, status=row.status, created_at=row.created_at)
