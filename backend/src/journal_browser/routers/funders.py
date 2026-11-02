"""/api/v1/{code}/funders: Jisc OPF funder picker + policy detail.

Funders are canon (not institution-scoped); only the UT-work attribution
is per institution. work_funders (migration 0049) may be absent — the
counts degrade to zeros instead of erroring."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import InstitutionDep
from ..models import JiscFunder
from ..schemas import (
    FunderDetailResponse,
    FunderListItem,
    FunderSearchResponse,
    FunderTopJournal,
)
from ..services import funders as funders_service

router = APIRouter(prefix="/funders", tags=["funders"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

DEFAULT_LIMIT = 25


def _to_item(
    funder: JiscFunder,
    urls: list[str],
    ids: set[str],
    counts: dict[str, int],
) -> FunderListItem:
    structured = bool((funder.publications_policy or {}).get("archiving_policy"))
    # Display the twin the works actually cite; bare-id keys everywhere.
    openalex_url = max(urls, key=lambda u: counts.get(str(u).rsplit("/", 1)[-1], 0), default=None)
    n_ut_works = sum(counts.get(bare, 0) for bare in ids)
    return FunderListItem(
        id=funder.id,
        name=funder.name,
        country=funder.country,
        url=funder.url,
        ror=funder.ror,
        fundref=funder.fundref,
        openalex_funder_id=openalex_url,
        policy_structured=structured,
        n_ut_works=n_ut_works,
    )


@router.get("", response_model=FunderSearchResponse)
async def search_funders(
    session: SessionDep,
    institution: InstitutionDep,
    q: Annotated[str | None, Query(max_length=200)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = DEFAULT_LIMIT,
) -> FunderSearchResponse:
    # The canon is ~200 rows: link, count and filter in Python instead of a
    # raw-SQL order-by over a conditionally-existing table.
    funders = (await session.execute(select(JiscFunder).order_by(JiscFunder.name))).scalars().all()
    counts = await funders_service.ut_work_counts(session, institution.id)
    canon = await funders_service.canon_links(session)
    needle = (q or "").strip().lower()
    items = []
    for funder in funders:
        if needle:
            haystack = [(funder.name or ""), *canon.aliases.get(funder.id, [])]
            if not any(needle in name.lower() for name in haystack):
                continue
        items.append(
            _to_item(
                funder, canon.urls.get(funder.id, []), canon.bare_ids.get(funder.id, set()), counts
            )
        )
    # Order: n_ut_works desc nulls last (counts default 0), then name.
    items.sort(key=lambda f: (-f.n_ut_works, (f.name or "").lower()))
    return FunderSearchResponse(items=items[offset : offset + limit], total=len(items))


@router.get("/{funder_id}", response_model=FunderDetailResponse)
async def funder_detail(
    funder_id: int, session: SessionDep, institution: InstitutionDep
) -> FunderDetailResponse:
    funder = await session.get(JiscFunder, funder_id)
    if funder is None:
        raise HTTPException(status_code=404, detail=f"funder {funder_id} not found")
    counts = await funders_service.ut_work_counts(session, institution.id)
    canon = await funders_service.canon_links(session)
    ids = canon.bare_ids.get(funder_id, set())
    item = _to_item(funder, sorted(ids), ids, counts)
    # Top journals across every twin the works may cite.
    top: list[dict[str, Any]] = []
    for bare in sorted(ids, key=lambda b: -counts.get(b, 0)):
        top.extend(await funders_service.top_journals(session, institution.id, bare))
    seen: set[str] = set()
    deduped = [j for j in top if not (j["issn_l"] in seen or seen.add(j["issn_l"]))]
    return FunderDetailResponse(
        **item.model_dump(),
        publications_policy=funder.publications_policy,
        data_archiving_policy=funder.data_archiving_policy,
        openaire=canon.openaire.get(funder_id),
        top_journals=[FunderTopJournal(**j) for j in deduped[:5]],
    )
