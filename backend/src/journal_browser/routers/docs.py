"""/api/v1/docs: the repo's markdown docs, parsed into blocks for the
frontend's /{inst}/docs pages. Overrides from doc_edits (admin PUT, see
routers/admin.py) are applied at read time, so edits land without touching
the source files."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..docs import list_docs, parse_blocks, read_doc
from ..models import DocEdit
from ..schemas import DocDetailOut, DocMetaOut

router = APIRouter(prefix="/docs", tags=["docs"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[DocMetaOut])
async def docs_index(session: SessionDep) -> list[dict[str, Any]]:
    edits = dict(
        (
            await session.execute(select(DocEdit.doc_slug, func.count()).group_by(DocEdit.doc_slug))
        ).all()
    )
    return [{**meta, "edits": edits.get(meta["slug"], 0)} for meta in list_docs()]


@router.get("/{slug}", response_model=DocDetailOut)
async def doc_detail(slug: str, session: SessionDep) -> dict[str, Any]:
    meta = read_doc(slug)
    if meta is None:
        raise HTTPException(404, f"unknown doc: {slug}")
    overrides = dict(
        (
            await session.execute(
                select(DocEdit.block_key, DocEdit.replacement).where(
                    DocEdit.doc_slug == meta["slug"]  # canonical form
                )
            )
        ).all()
    )
    blocks = []
    for i, block in enumerate(parse_blocks(meta.pop("markdown"))):
        key = f"b{i:03d}"
        replacement = overrides.get(key)
        blocks.append(
            {
                "key": key,
                **block,
                "text": replacement if replacement is not None else block["text"],
                "edited": replacement is not None,
            }
        )
    return {**meta, "blocks": blocks}
