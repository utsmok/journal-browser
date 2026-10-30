from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select

from ...docs import read_doc
from ...models import DocEdit
from ...schemas import DocEditOut
from .auth import AdminDep, SessionDep

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Doc block edits ─────────────────────────────────────────────────────────
# Overrides for single blocks of the served markdown docs (docs/). Stored in
# doc_edits, applied at read time by routers/docs.py; the source files stay
# untouched. original_hash records what the editor saw, provenance only.

class DocEditIn(BaseModel):
    block_key: str
    original_hash: str
    replacement: str


@router.put("/docs/{slug}/edits", response_model=DocEditOut)
async def put_doc_edit(
    slug: str, body: DocEditIn, session: SessionDep, _: AdminDep
) -> dict[str, Any]:
    if read_doc(slug) is None:
        raise HTTPException(404, f"unknown doc: {slug}")
    slug = read_doc(slug)["slug"]  # canonical lower-case form
    if not body.replacement.strip():
        raise HTTPException(422, "replacement must not be empty")
    row = await session.scalar(
        select(DocEdit).where(
            DocEdit.doc_slug == slug, DocEdit.block_key == body.block_key
        )
    )
    if row is None:
        row = DocEdit(doc_slug=slug, block_key=body.block_key)
        session.add(row)
    row.original_hash = body.original_hash
    row.replacement = body.replacement
    await session.commit()
    return {"slug": slug, "block_key": body.block_key, "edited": True}


@router.delete("/docs/{slug}/edits/{block_key}", status_code=204)
async def delete_doc_edit(
    slug: str, block_key: str, session: SessionDep, _: AdminDep
) -> None:
    slug = slug.lower()
    await session.execute(
        delete(DocEdit).where(
            DocEdit.doc_slug == slug, DocEdit.block_key == block_key
        )
    )
    await session.commit()
