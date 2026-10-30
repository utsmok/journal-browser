"""Admin review of the author identity cascade: list + status flips.

GET /admin/author-identities lists resolution rows (filter by status or
institution) with the local author's display name joined in.
PUT /admin/author-identities flips one row's status. Flips are sticky:
the resolver's upsert never lowers an explicit confirmed/rejected
decision (candidates follow new evidence). A flip changes the additive
`authors.openalex_ids` build only at the next authors ingest, and
'rejected' rows keep the cascade from re-proposing the same id.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select

from ...models import Author, AuthorIdentity, Institution
from ...schemas import AuthorIdentityAdminOut
from .auth import AdminDep, SessionDep

router = APIRouter(prefix="/admin", tags=["admin"])

IDENTITY_STATUSES = ("confirmed", "candidate", "rejected")


class IdentityStatusIn(BaseModel):
    institution_id: int
    author_pure_uuid: str
    source: str = "openalex"
    external_id: str
    status: str


@router.get("/author-identities", response_model=list[AuthorIdentityAdminOut])
async def list_author_identities(
    session: SessionDep,
    _: AdminDep,
    status: str | None = Query(default=None),
    institution: str | None = Query(default=None, description="institution code"),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[dict[str, Any]]:
    """Identity rows, newest activity first, with the local author name."""
    if status is not None and status not in IDENTITY_STATUSES:
        raise HTTPException(422, f"status must be one of {list(IDENTITY_STATUSES)}")
    stmt = (
        select(AuthorIdentity, Institution.code, Author.name)
        .select_from(AuthorIdentity)
        .join(Institution, Institution.id == AuthorIdentity.institution_id)
        .outerjoin(
            Author,
            (Author.institution_id == AuthorIdentity.institution_id)
            & (Author.pure_uuid == AuthorIdentity.author_pure_uuid),
        )
        .order_by(desc(AuthorIdentity.updated_at))
        .limit(limit)
    )
    if status is not None:
        stmt = stmt.where(AuthorIdentity.status == status)
    if institution is not None:
        stmt = stmt.where(Institution.code == institution)
    rows = (await session.execute(stmt)).all()
    return [
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
    ]


@router.put("/author-identities", response_model=AuthorIdentityAdminOut)
async def set_identity_status(
    body: IdentityStatusIn, session: SessionDep, _: AdminDep
) -> dict[str, Any]:
    """Flip one identity row (institution + author + source + external id).

    The row is keyed by its full PK, sent in the body. 'rejected' is
    sticky: re-runs keep it out of authors.openalex_ids and never
    re-promote it. 'confirmed' forces the id into the next ingest's
    additive openalex_ids build even if the cascade demotes it."""
    if body.status not in IDENTITY_STATUSES:
        raise HTTPException(422, f"status must be one of {list(IDENTITY_STATUSES)}")
    row = await session.get(
        AuthorIdentity,
        (body.institution_id, body.author_pure_uuid, body.source, body.external_id),
    )
    if row is None:
        raise HTTPException(404, "identity row not found")
    row.status = body.status
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
    await session.commit()
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
