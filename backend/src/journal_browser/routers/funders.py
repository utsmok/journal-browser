"""/api/v1/{code}/funders: Jisc OPF funder picker + policy detail.

Funders are canon (not institution-scoped); only the UT-work attribution
is per institution. work_funders (migration 0049) may be absent — the
counts degrade to zeros instead of erroring."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import InstitutionDep
from ..models import JiscFunder, OpenaireFunder, OpenalexFunder
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


async def _openalex_links(session: AsyncSession) -> dict[int, str]:
    """jisc_funders.id -> openalex_funder_id, ROR-preferred over FundRef,
    in two keyed queries (the canon is ~200 rows; 39k openalex funders)."""
    ror_rows = await session.execute(
        select(JiscFunder.id, OpenalexFunder.openalex_id)
        .select_from(JiscFunder)
        .join(OpenalexFunder, OpenalexFunder.ror == JiscFunder.ror)
        .where(JiscFunder.ror.is_not(None))
    )
    ref_rows = await session.execute(
        select(JiscFunder.id, OpenalexFunder.openalex_id)
        .select_from(JiscFunder)
        .join(OpenalexFunder, OpenalexFunder.fundref == JiscFunder.fundref)
        .where(JiscFunder.ror.is_(None), JiscFunder.fundref.is_not(None))
    )
    links = dict(ref_rows.all())
    links.update(dict(ror_rows.all()))
    return links


async def _search_aliases(session: AsyncSession) -> dict[int, list[str]]:
    """jisc_funders.id -> extra searchable names from linked canon rows:
    OpenAlex display names (e.g. the Dutch name for NWO) and OpenAIRE
    short names (e.g. "NWO"). Canon-linked, so no invented aliases."""
    ror_rows = await session.execute(
        select(JiscFunder.id, OpenalexFunder.display_name, OpenaireFunder.short_name)
        .select_from(JiscFunder)
        .outerjoin(OpenalexFunder, OpenalexFunder.ror == JiscFunder.ror)
        .outerjoin(OpenaireFunder, OpenaireFunder.ror == JiscFunder.ror)
        .where(JiscFunder.ror.is_not(None))
    )
    ref_rows = await session.execute(
        select(JiscFunder.id, OpenalexFunder.display_name, OpenaireFunder.short_name)
        .select_from(JiscFunder)
        .outerjoin(OpenalexFunder, OpenalexFunder.fundref == JiscFunder.fundref)
        .outerjoin(OpenaireFunder, OpenaireFunder.ror == JiscFunder.ror)
        .where(JiscFunder.ror.is_(None), JiscFunder.fundref.is_not(None))
    )
    aliases: dict[int, list[str]] = {}
    for funder_id, display_name, short_name in (*ror_rows.all(), *ref_rows.all()):
        bucket = aliases.setdefault(funder_id, [])
        for value in (display_name, short_name):
            if value and value not in bucket:
                bucket.append(value)
    return aliases


def _to_item(
    funder: JiscFunder,
    openalex_funder_id: str | None,
    counts: dict[str, int],
) -> FunderListItem:
    structured = bool((funder.publications_policy or {}).get("archiving_policy"))
    return FunderListItem(
        id=funder.id,
        name=funder.name,
        country=funder.country,
        url=funder.url,
        ror=funder.ror,
        fundref=funder.fundref,
        openalex_funder_id=openalex_funder_id,
        policy_structured=structured,
        n_ut_works=counts.get(openalex_funder_id, 0),
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
    links = await _openalex_links(session)
    aliases = await _search_aliases(session)
    needle = (q or "").strip().lower()
    items = []
    for funder in funders:
        if needle:
            haystack = [(funder.name or ""), *aliases.get(funder.id, [])]
            if not any(needle in name.lower() for name in haystack):
                continue
        items.append(_to_item(funder, links.get(funder.id), counts))
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
    links = await _openalex_links(session)
    openalex_funder_id = links.get(funder_id)
    counts = await funders_service.ut_work_counts(session, institution.id)
    top = await funders_service.top_journals(session, institution.id, openalex_funder_id)
    return FunderDetailResponse(
        **_to_item(funder, openalex_funder_id, counts).model_dump(),
        publications_policy=funder.publications_policy,
        data_archiving_policy=funder.data_archiving_policy,
        top_journals=[FunderTopJournal(**j) for j in top],
    )
