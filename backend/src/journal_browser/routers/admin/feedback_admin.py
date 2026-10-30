from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from ...models import Feedback
from ...schemas import FeedbackAdminOut, FeedbackPatchOut
from ...vocab import FeedbackPriority, FeedbackStatus
from .auth import AdminDep, SessionDep

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Feedback triage ────────────────────────────────────────────────────────

FEEDBACK_STATUSES = tuple(FeedbackStatus)
FEEDBACK_PRIORITIES = tuple(FeedbackPriority)


class FeedbackUpdateIn(BaseModel):
    status: str | None = None
    priority: str | None = None
    resolution_notes: str | None = Field(default=None, max_length=8000)


@router.get("/feedback", response_model=list[FeedbackAdminOut])
async def list_feedback(
    session: SessionDep,
    _: AdminDep,
    status: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
) -> list[dict[str, Any]]:
    if status is not None and status not in FEEDBACK_STATUSES:
        raise HTTPException(422, f"status must be one of {list(FEEDBACK_STATUSES)}")
    stmt = select(Feedback).order_by(desc(Feedback.created_at)).limit(limit)
    if status is not None:
        stmt = (
            select(Feedback)
            .where(Feedback.status == status)
            .order_by(desc(Feedback.created_at))
            .limit(limit)
        )
    rows = (await session.scalars(stmt)).all()
    return [
        {
            "id": r.id,
            "title": r.title,
            "description": r.description,
            "category": r.category,
            "status": r.status,
            "priority": r.priority,
            "page_url": r.page_url,
            "page_data": r.page_data,
            "resolution_notes": r.resolution_notes,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
        }
        for r in rows
    ]


@router.patch("/feedback/{feedback_id}", response_model=FeedbackPatchOut)
async def update_feedback(
    feedback_id: int, body: FeedbackUpdateIn, session: SessionDep, _: AdminDep
) -> dict[str, Any]:
    if body.status is not None and body.status not in FEEDBACK_STATUSES:
        raise HTTPException(422, f"status must be one of {list(FEEDBACK_STATUSES)}")
    if body.priority is not None and body.priority not in FEEDBACK_PRIORITIES:
        raise HTTPException(422, f"priority must be one of {list(FEEDBACK_PRIORITIES)}")
    row = await session.get(Feedback, feedback_id)
    if row is None:
        raise HTTPException(404, "feedback not found")
    if body.status is not None:
        row.status = body.status
    if body.priority is not None:
        row.priority = body.priority
    if body.resolution_notes is not None:
        row.resolution_notes = body.resolution_notes
    row.updated_at = datetime.now(UTC)
    await session.commit()
    return {"id": row.id, "status": row.status, "priority": row.priority}


@router.delete("/feedback/{feedback_id}", status_code=204)
async def delete_feedback(
    feedback_id: int, session: SessionDep, _: AdminDep
) -> None:
    row = await session.get(Feedback, feedback_id)
    if row is None:
        raise HTTPException(404, "feedback not found")
    await session.delete(row)
    await session.commit()
