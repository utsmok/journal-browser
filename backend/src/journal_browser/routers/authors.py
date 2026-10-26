"""/api/v1/{code}/authors: author roster + profile, ut-metadata ingest."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..routers.institutions import InstitutionDep
from ..schemas import (
    AuthorAlternative,
    AuthorProfileResponse,
    AuthorSearchResponse,
    AuthorSimilarBundle,
    AuthorSimilarJournal,
)
from ..services import authors as authors_service

router = APIRouter(prefix="/authors", tags=["authors"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=AuthorSearchResponse)
async def search_authors(
    session: SessionDep,
    institution: InstitutionDep,
    q: str | None = None,
    limit: int = Query(authors_service.DEFAULT_LIMIT, ge=1, le=authors_service.MAX_LIMIT),
) -> AuthorSearchResponse:
    return AuthorSearchResponse(
        **await authors_service.search_authors(session, institution.id, q, limit)
    )


@router.get("/{pure_uuid}", response_model=AuthorProfileResponse)
async def author_profile(
    pure_uuid: str, session: SessionDep, institution: InstitutionDep
) -> AuthorProfileResponse:
    profile = await authors_service.author_profile(session, institution.id, pure_uuid)
    if profile is None:
        raise HTTPException(status_code=404, detail="author not found")
    return AuthorProfileResponse(
        author=profile["author"],
        oa_by_year=profile["oa_by_year"],
        journals=profile["journals"],
        topics=profile["topics"],
        similar=AuthorSimilarBundle(
            **{
                key: [AuthorSimilarJournal(**item) for item in items]
                for key, items in profile["similar"].items()
            }
        ),
        alternatives=[
            AuthorAlternative(
                **{
                    **alt,
                    "options": [AuthorSimilarJournal(**option) for option in alt["options"]],
                }
            )
            for alt in profile["alternatives"]
        ],
        works=profile["works"],
    )
