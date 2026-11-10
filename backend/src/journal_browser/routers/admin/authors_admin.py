"""Admin review of the author identity cascade: list + status flips.

GET /admin/author-identities lists resolution rows (filter by status or
institution) with the local author's display name joined in.
PUT /admin/author-identities flips one row's status. Flips are sticky:
the resolver's upsert never lowers an explicit confirmed/rejected
decision (candidates follow new evidence). A flip changes the additive
`authors.openalex_ids` build only at the next authors ingest, and
'rejected' rows keep the cascade from re-proposing the same id.
Every actual flip appends a status_changes audit row (see audit_admin).
"""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select

from ...models import (
    Author,
    AuthorIdentity,
    HarvestRun,
    Institution,
    OpenalexWork,
    SourceRecord,
    StatusChangeLog,
)
from ...schemas import AdminExternalAuthorOut, AuthorIdentityAdminOut, AuthorIdentityPageOut
from ...services.authorship import attributed_to_any
from .auth import AdminDep, SessionDep
from .settings_admin import _get_institution_or_404

router = APIRouter(prefix="/admin", tags=["admin"])

IDENTITY_STATUSES = ("confirmed", "candidate", "rejected")


class IdentityStatusIn(BaseModel):
    institution_id: int
    author_pure_uuid: str
    source: str = "openalex"
    external_id: str
    status: str
    # Optional provenance for the audit row; auth is one shared token, so
    # the body is the only place a reviewer name can come from.
    changed_by: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=2000)


@router.get("/author-identities", response_model=AuthorIdentityPageOut)
async def list_author_identities(
    session: SessionDep,
    _: AdminDep,
    status: str | None = Query(default=None),
    institution: str | None = Query(default=None, description="institution code"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
) -> AuthorIdentityPageOut:
    """Identity rows, newest activity first, with the local author name.

    Server-paged via offset/limit; total is the full filtered count.
    """
    if status is not None and status not in IDENTITY_STATUSES:
        raise HTTPException(422, f"status must be one of {list(IDENTITY_STATUSES)}")
    filtered = (
        select(AuthorIdentity, Institution.code, Author.name)
        .select_from(AuthorIdentity)
        .join(Institution, Institution.id == AuthorIdentity.institution_id)
        .outerjoin(
            Author,
            (Author.institution_id == AuthorIdentity.institution_id)
            & (Author.pure_uuid == AuthorIdentity.author_pure_uuid),
        )
    )
    if status is not None:
        filtered = filtered.where(AuthorIdentity.status == status)
    if institution is not None:
        filtered = filtered.where(Institution.code == institution)
    total = await session.scalar(select(func.count()).select_from(filtered.subquery()))
    rows = (
        await session.execute(
            filtered.order_by(desc(AuthorIdentity.updated_at)).offset(offset).limit(limit)
        )
    ).all()
    return AuthorIdentityPageOut(
        total=total or 0,
        offset=offset,
        items=[
            {
                "institution_id": row.institution_id,
                "institution_code": code,
                "author_pure_uuid": row.author_pure_uuid,
                "author_name": name,
                "source": row.source,
                "external_id": row.external_id,
                "status": row.status,
                "method": row.method,
                "confidence": row.confidence,
                "n_works": row.n_works,
                "orcid_corroborated": row.orcid_corroborated,
                "evidence": row.evidence,
                "updated_at": row.updated_at,
            }
            for row, code, name in rows
        ],
    )


@router.put("/author-identities", response_model=AuthorIdentityAdminOut)
async def set_identity_status(
    body: IdentityStatusIn, session: SessionDep, _: AdminDep
) -> dict[str, Any]:
    """Flip one identity row (institution + author + source + external id).

    The row is keyed by its full PK, sent in the body. 'rejected' is
    sticky: re-runs keep it out of authors.openalex_ids and never
    re-promote it. 'confirmed' forces the id into the next ingest's
    additive openalex_ids build even if the cascade demotes it.

    Every actual transition appends a status_changes audit row; a no-op
    (status already the requested value) changes nothing and records
    nothing.
    """
    if body.status not in IDENTITY_STATUSES:
        raise HTTPException(422, f"status must be one of {list(IDENTITY_STATUSES)}")
    row = await session.get(
        AuthorIdentity,
        (body.institution_id, body.author_pure_uuid, body.source, body.external_id),
    )
    if row is None:
        raise HTTPException(404, "identity row not found")
    if row.status == body.status:
        return await _identity_payload(session, row)
    old_status = row.status
    row.status = body.status
    # The review list orders by updated_at ("newest activity first"), so a
    # flip counts as activity.
    row.updated_at = datetime.now(UTC)
    session.add(
        StatusChangeLog(
            table_name="author_identities",
            row_key={
                "institution_id": body.institution_id,
                "author_pure_uuid": body.author_pure_uuid,
                "source": body.source,
                "external_id": body.external_id,
            },
            old_value=old_status,
            new_value=body.status,
            note=body.note,
            changed_by=body.changed_by,
        )
    )
    await session.commit()
    return await _identity_payload(session, row)


async def _identity_payload(session: SessionDep, row: AuthorIdentity) -> dict[str, Any]:
    inst_code = await session.scalar(
        select(Institution.code).where(Institution.id == row.institution_id)
    )
    author_name = await session.scalar(
        select(Author.name)
        .where(
            Author.institution_id == row.institution_id,
            Author.pure_uuid == row.author_pure_uuid,
        )
        .limit(1)
    )
    return {
        "institution_id": row.institution_id,
        "institution_code": inst_code,
        "author_pure_uuid": row.author_pure_uuid,
        "author_name": author_name,
        "source": row.source,
        "external_id": row.external_id,
        "status": row.status,
        "method": row.method,
        "confidence": row.confidence,
        "n_works": row.n_works,
        "orcid_corroborated": row.orcid_corroborated,
        "evidence": row.evidence,
        "updated_at": row.updated_at,
    }


@router.get("/external-author/{external_id}", response_model=AdminExternalAuthorOut)
async def stored_external_author(
    external_id: str,
    session: SessionDep,
    _: AdminDep,
    institution: Annotated[str | None, Query(max_length=32)] = None,
) -> dict[str, Any]:
    """The harvest's stored OpenAlex author profile + recent works.

    The review drawer reads the verbatim source_records payload (the listing
    sweep lands every institutional author profile there) plus a recent-works
    sample from the openalex_works projection — no live API call. 404 when
    this id was never swept; the UI falls back to an OpenAlex link.
    """
    record = (
        await session.execute(
            select(SourceRecord)
            .join(HarvestRun, HarvestRun.id == SourceRecord.harvest_run_id)
            .where(
                SourceRecord.source == "openalex",
                SourceRecord.entity_type == "authors",
                SourceRecord.source_pk == external_id,
            )
            .order_by(desc(SourceRecord.id))
            .limit(1)
        )
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(404, f"no stored OpenAlex profile for {external_id}")

    # Same indexed attribution probe as the gap queries (edge-table rows
    # store lower-cased bare ids).
    conditions = [attributed_to_any([external_id])]
    if institution is not None:
        inst = await _get_institution_or_404(session, institution)
        conditions.append(OpenalexWork.institution_id == inst.id)
    works = (
        (
            await session.execute(
                select(OpenalexWork)
                .where(*conditions)
                .order_by(desc(OpenalexWork.year), OpenalexWork.w_id)
                .limit(8)
            )
        )
        .scalars()
        .all()
    )
    return {
        "source_pk": record.source_pk,
        "harvested_at": record.harvested_at,
        "author": record.payload,
        "works": [
            {
                "w_id": work.w_id,
                "title": work.title,
                "year": work.year,
                "doi": work.doi_normalized,
                "venue": work.venue_name,
            }
            for work in works
        ],
    }
