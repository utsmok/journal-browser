"""Read access to the status_changes audit log.

Every admin status flip (author identities, work identities, feedback
triage) appends a row there; this endpoint lists them, newest first.
There is no write surface: the log is append-only by design.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import desc, select

from ...models import StatusChangeLog
from ...schemas import StatusChangeOut
from .auth import AdminDep, SessionDep

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/status-changes", response_model=list[StatusChangeOut])
async def list_status_changes(
    session: SessionDep,
    _: AdminDep,
    table_name: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[dict[str, Any]]:
    """Audited status flips, newest first, optionally per subject table."""
    stmt = select(StatusChangeLog).order_by(desc(StatusChangeLog.id)).limit(limit)
    if table_name is not None:
        stmt = stmt.where(StatusChangeLog.table_name == table_name)
    rows = (await session.scalars(stmt)).all()
    return [
        {
            "id": row.id,
            "table_name": row.table_name,
            "row_key": row.row_key,
            "field": row.field,
            "old_value": row.old_value,
            "new_value": row.new_value,
            "note": row.note,
            "changed_by": row.changed_by,
            "changed_at": row.changed_at,
        }
        for row in rows
    ]
