"""/api/v1/{code}/authors: author roster + profile, ut-metadata ingest."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import InstitutionDep
from ..schemas import (
    AuthorAlternative,
    AuthorOpenalexOnly,
    AuthorProfileResponse,
    AuthorSearchResponse,
    AuthorSimilarBundle,
    AuthorSimilarJournal,
)
from ..services import authors as authors_service
from ..services import exports as exports_service
from ..services.works_query import clamped_year_range

router = APIRouter(prefix="/authors", tags=["authors"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=AuthorSearchResponse)
async def search_authors(
    session: SessionDep,
    institution: InstitutionDep,
    q: str | None = None,
    limit: int = Query(authors_service.DEFAULT_LIMIT, ge=1, le=authors_service.MAX_LIMIT),
    faculty: Annotated[str | None, Query(max_length=200)] = None,
    org: Annotated[str | None, Query(max_length=200)] = None,
    has_orcid: Annotated[Literal["yes", "no"] | None, Query()] = None,
    works: Annotated[str | None, Query(max_length=60)] = None,
    last_pub: Annotated[str | None, Query(max_length=60)] = None,
    topic: Annotated[str | None, Query(max_length=200)] = None,
    sort: Annotated[Literal["works_desc", "name_asc", "name_desc", "last_pub_desc"], Query()] = (
        "works_desc"
    ),
    offset: Annotated[int, Query(ge=0)] = 0,
    year_from: Annotated[
        int | None,
        Query(
            ge=1900,
            le=2100,
            description="Publication-year range start (clamped to the "
            "institution's data window; default: the full window)",
        ),
    ] = None,
    year_to: Annotated[
        int | None,
        Query(
            ge=1900,
            le=2100,
            description="Publication-year range end (clamped to the "
            "institution's data window; default: the full window)",
        ),
    ] = None,
) -> AuthorSearchResponse:
    # Comma-separated multi-selects, OR'd within a dimension, AND'd across
    # dimensions (the journals oa_type convention). Unknown values match
    # nothing: empty result, no error.
    def _split(raw: str | None) -> list[str] | None:
        # "|" not ",": faculty/org/topic values contain commas
        values = [v for v in (raw or "").split("|") if v]
        return values or None

    return AuthorSearchResponse(
        **await authors_service.search_authors(
            session,
            institution.id,
            q,
            limit,
            require_confirmed=institution.require_confirmed_affiliation,
            faculty=_split(faculty),
            org=_split(org),
            has_orcid=has_orcid,
            works=_split(works),
            last_pub=_split(last_pub),
            topic=_split(topic),
            sort=sort,
            offset=offset,
            year_range=clamped_year_range(institution, year_from, year_to),
        )
    )


@router.get("/{pure_uuid}", response_model=AuthorProfileResponse)
async def author_profile(
    pure_uuid: str,
    session: SessionDep,
    institution: InstitutionDep,
    year_from: Annotated[
        int | None,
        Query(
            ge=1900,
            le=2100,
            description="Publication-year range start (clamped to the "
            "institution's data window; default: the full window)",
        ),
    ] = None,
    year_to: Annotated[
        int | None,
        Query(
            ge=1900,
            le=2100,
            description="Publication-year range end (clamped to the "
            "institution's data window; default: the full window)",
        ),
    ] = None,
) -> AuthorProfileResponse:
    profile = await authors_service.author_profile(
        session,
        institution,
        pure_uuid,
        year_range=clamped_year_range(institution, year_from, year_to),
    )
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
        openalex_only=AuthorOpenalexOnly(**profile["openalex_only"]),
        openalex_only_count=profile["openalex_only_count"],
    )


@router.get("/{pure_uuid}/avatar")
async def author_avatar(
    pure_uuid: str, session: SessionDep, institution: InstitutionDep
) -> Response:
    """The author's people.utwente.nl portrait: uuid-verified matches
    (or admin-confirmed candidates) only; 404 otherwise."""
    avatar = await authors_service.author_avatar(session, institution, pure_uuid)
    if avatar is None:
        raise HTTPException(status_code=404, detail="no avatar")
    content, media_type = avatar
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/{pure_uuid}/works.csv")
async def author_works_csv(
    pure_uuid: str,
    session: SessionDep,
    institution: InstitutionDep,
    scope: str = "missed",
    year_from: Annotated[
        int | None,
        Query(
            ge=1900,
            le=2100,
            description="Publication-year range start (clamped to the "
            "institution's data window; default: the full window)",
        ),
    ] = None,
    year_to: Annotated[
        int | None,
        Query(
            ge=1900,
            le=2100,
            description="Publication-year range end (clamped to the "
            "institution's data window; default: the full window)",
        ),
    ] = None,
) -> StreamingResponse:
    """Uncapped CSV of the author's works: scope=missed (default) serves
    the openalex-only list, scope=canon the Pure works; 400 otherwise."""
    return await exports_service.author_works_csv(
        session,
        institution,
        pure_uuid,
        scope,
        year_range=clamped_year_range(institution, year_from, year_to),
    )
