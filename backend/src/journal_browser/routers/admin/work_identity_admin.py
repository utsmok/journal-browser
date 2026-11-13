"""Admin review of cross-source work identities: list + status flips.

GET /admin/work-identities lists work_identity rows (filter by status,
institution, or source) with the work's title joined in. This is the
in-app half of the loop that used to close only via the curation report
file. PUT /admin/work-identities flips one row's status; POST
/admin/work-identities/bulk applies many rows for one reviewer in a
single transaction. Flips are durable by construction — every harvest
write is on_conflict_do_nothing, so re-runs never touch an existing
row — and every actual transition appends a status_changes audit row.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select

from ...models import Institution, StatusChangeLog, Work, WorkIdentity
from ...schemas import (
    WorkIdentityAdminOut,
    WorkIdentityBulkIn,
    WorkIdentityBulkOut,
    WorkIdentityPageOut,
)
from .auth import AdminDep, SessionDep

router = APIRouter(prefix="/admin", tags=["admin"])

WORK_IDENTITY_STATUSES = ("confirmed", "missing", "candidate")


class WorkIdentityStatusIn(BaseModel):
    institution_id: int
    source: str
    source_pk: str
    status: str
    changed_by: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=2000)


@router.get("/work-identities", response_model=WorkIdentityPageOut)
async def list_work_identities(
    session: SessionDep,
    _: AdminDep,
    status: str | None = Query(default=None),
    institution: str | None = Query(default=None, description="institution code"),
    source: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
) -> WorkIdentityPageOut:
    """Identity rows, newest activity first, with the work title.

    Server-paged via offset/limit; total is the full filtered count.
    """
    if status is not None and status not in WORK_IDENTITY_STATUSES:
        raise HTTPException(422, f"status must be one of {list(WORK_IDENTITY_STATUSES)}")
    filtered = (
        select(WorkIdentity, Institution.code, Work.title)
        .select_from(WorkIdentity)
        .join(Institution, Institution.id == WorkIdentity.institution_id)
        .outerjoin(
            Work,
            (Work.institution_id == WorkIdentity.institution_id)
            & (Work.pure_uuid == WorkIdentity.work_id),
        )
    )
    if status is not None:
        filtered = filtered.where(WorkIdentity.status == status)
    if institution is not None:
        filtered = filtered.where(Institution.code == institution)
    if source is not None:
        filtered = filtered.where(WorkIdentity.source == source)
    total = await session.scalar(select(func.count()).select_from(filtered.subquery()))
    rows = (
        await session.execute(
            filtered.order_by(desc(WorkIdentity.updated_at), desc(WorkIdentity.id))
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return WorkIdentityPageOut(
        total=total or 0,
        offset=offset,
        items=[
            {
                "institution_id": row.institution_id,
                "institution_code": code,
                "work_id": row.work_id,
                "work_title": title,
                "source": row.source,
                "source_pk": row.source_pk,
                "matched_by": row.matched_by,
                "confidence": row.confidence,
                "status": row.status,
                "note": row.note,
                "updated_at": row.updated_at,
            }
            for row, code, title in rows
        ],
    )


@router.put("/work-identities", response_model=WorkIdentityAdminOut)
async def set_work_identity_status(
    body: WorkIdentityStatusIn, session: SessionDep, _: AdminDep
) -> dict[str, Any]:
    """Flip one work-identity row (institution + source + source_pk).

    Any status flip is allowed — including un-rejecting — because the
    review surface has no other undo. A flip writes a status_changes
    audit row; a no-op changes nothing and records nothing.
    """
    if body.status not in WORK_IDENTITY_STATUSES:
        raise HTTPException(422, f"status must be one of {list(WORK_IDENTITY_STATUSES)}")
    try:
        await apply_decision(
            session,
            institution_id=body.institution_id,
            source=body.source,
            source_pk=body.source_pk,
            status=body.status,
            note=body.note,
            reviewer=body.changed_by,
        )
    except ValueError as exc:
        raise HTTPException(404, "work identity row not found") from exc
    await session.commit()
    row = await session.scalar(
        select(WorkIdentity).where(
            WorkIdentity.institution_id == body.institution_id,
            WorkIdentity.source == body.source,
            WorkIdentity.source_pk == body.source_pk,
        )
    )
    return await _identity_payload(session, row)


@router.post("/work-identities/bulk", response_model=WorkIdentityBulkOut)
async def bulk_work_identity_decisions(
    body: WorkIdentityBulkIn, session: SessionDep, _: AdminDep
) -> WorkIdentityBulkOut:
    """Apply one reviewer's decisions to many work-identity rows.

    One transaction: each row that exists gets the same audited flip the
    PUT does; unknown rows land in `errors` without aborting the batch.
    An unexpected database error rolls the whole batch back.
    """
    outcomes = {"confirmed": 0, "missing": 0, "reopened": 0, "unchanged": 0}
    errors: list[dict[str, str]] = []
    try:
        for update in body.updates:
            try:
                result = await apply_decision(
                    session,
                    institution_id=body.institution_id,
                    source=body.source,
                    source_pk=update.source_pk,
                    status=update.status,
                    note=update.note,
                    reviewer=body.reviewer,
                )
            except ValueError as exc:
                errors.append({"source_pk": update.source_pk, "error": str(exc)})
                continue
            outcomes[result] += 1
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise HTTPException(500, "bulk update failed; rolled back") from exc
    return WorkIdentityBulkOut(
        confirmed=outcomes["confirmed"],
        missing=outcomes["missing"],
        reopened=outcomes["reopened"],
        unchanged=outcomes["unchanged"],
        errors=errors,
    )


async def apply_decision(
    session: SessionDep,
    *,
    institution_id: int,
    source: str,
    source_pk: str,
    status: str,
    note: str | None,
    reviewer: str | None,
) -> str:
    """Apply one review decision to a work-identity row, without committing.

    Returns what happened: 'confirmed', 'missing', 'reopened' (back to
    candidate), or 'unchanged' (no transition, no audit row). Raises
    ValueError when the row does not exist. The caller owns the
    transaction: the PUT commits per row, the bulk endpoint and the
    bulk_review CLI commit once for the whole batch.
    """
    row = await session.scalar(
        select(WorkIdentity).where(
            WorkIdentity.institution_id == institution_id,
            WorkIdentity.source == source,
            WorkIdentity.source_pk == source_pk,
        )
    )
    if row is None:
        raise ValueError(f"work identity row not found: {source_pk}")
    if row.status == status:
        return "unchanged"
    old_status = row.status
    row.status = status
    session.add(
        StatusChangeLog(
            table_name="work_identity",
            row_key={
                "institution_id": institution_id,
                "source": source,
                "source_pk": source_pk,
            },
            old_value=old_status,
            new_value=status,
            note=note,
            changed_by=reviewer,
        )
    )
    if status == "confirmed":
        return "confirmed"
    if status == "missing":
        return "missing"
    return "reopened"


async def _identity_payload(session: SessionDep, row: WorkIdentity) -> dict[str, Any]:
    inst_code = await session.scalar(
        select(Institution.code).where(Institution.id == row.institution_id)
    )
    title = await session.scalar(
        select(Work.title).where(
            Work.institution_id == row.institution_id,
            Work.pure_uuid == row.work_id,
        )
    )
    return {
        "institution_id": row.institution_id,
        "institution_code": inst_code,
        "work_id": row.work_id,
        "work_title": title,
        "source": row.source,
        "source_pk": row.source_pk,
        "matched_by": row.matched_by,
        "confidence": row.confidence,
        "status": row.status,
        "note": row.note,
        "updated_at": row.updated_at,
    }
