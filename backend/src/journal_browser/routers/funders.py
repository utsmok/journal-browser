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
from ..services.works_query import clamped_year_range
from .params import split_multi

router = APIRouter(prefix="/funders", tags=["funders"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

DEFAULT_LIMIT = 25


def _to_item(
    funder: JiscFunder,
    urls: list[str],
    ids: set[str],
    counts: dict[str, int],
    n_ut_works: int,
) -> FunderListItem:
    structured = bool((funder.publications_policy or {}).get("archiving_policy"))
    # Display the twin the works actually cite (per-id counts); bare-id
    # keys everywhere. n_ut_works is the twin-set-deduped count from
    # ut_funder_work_counts: one work crediting two stream twins of the
    # same funder counts once.
    openalex_url = max(urls, key=lambda u: counts.get(str(u).rsplit("/", 1)[-1], 0), default=None)
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
    country: Annotated[str | None, Query(max_length=200)] = None,
    policy_structured: bool | None = None,
    sort: Annotated[str | None, Query(pattern="^(works|name)$")] = None,
    dir: Annotated[str | None, Query(pattern="^(asc|desc)$")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = DEFAULT_LIMIT,
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
) -> FunderSearchResponse:
    # The canon is ~200 rows: link, count and filter in Python instead of a
    # raw-SQL order-by over a conditionally-existing table.
    funders = (await session.execute(select(JiscFunder).order_by(JiscFunder.name))).scalars().all()
    year_range = clamped_year_range(institution, year_from, year_to)
    counts = await funders_service.ut_work_counts(session, institution, year_range)
    canon = await funders_service.canon_links(session)
    union_counts = await funders_service.ut_funder_work_counts(
        session, institution, canon.bare_ids, year_range
    )
    needle = (q or "").strip().lower()
    base_items: list[FunderListItem] = []
    for funder in funders:
        if needle:
            haystack = [(funder.name or ""), *canon.aliases.get(funder.id, [])]
            if not any(needle in name.lower() for name in haystack):
                continue
        base_items.append(
            _to_item(
                funder,
                canon.urls.get(funder.id, []),
                canon.bare_ids.get(funder.id, set()),
                counts,
                union_counts.get(funder.id, 0),
            )
        )

    countries = {c.strip().upper() for c in (split_multi(country) or []) if c.strip()}

    def _matches(
        item: FunderListItem, *, use_country: bool = True, use_policy: bool = True
    ) -> bool:
        if use_country and countries and (item.country or "").upper() not in countries:
            return False
        return not (
            use_policy
            and policy_structured is not None
            and item.policy_structured != policy_structured
        )

    # Drop-own-dimension facets over the query-matched base.
    country_counts: dict[str, int] = {}
    for item in base_items:
        if not _matches(item, use_country=False, use_policy=True):
            continue
        code = (item.country or "").strip().upper()
        if code:
            country_counts[code] = country_counts.get(code, 0) + 1
    policy_counts = {"true": 0, "false": 0}
    for item in base_items:
        if not _matches(item, use_country=True, use_policy=False):
            continue
        key = "true" if item.policy_structured else "false"
        policy_counts[key] += 1
    facets: dict[str, dict[str, int]] = {
        "country": dict(sorted(country_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "policy_structured": policy_counts,
    }

    items = [item for item in base_items if _matches(item)]
    sort_key = sort or "works"
    if sort_key == "name":
        items.sort(key=lambda f: ((f.name or "").lower(), -f.n_ut_works), reverse=(dir == "desc"))
    elif dir == "asc":
        items.sort(key=lambda f: (f.n_ut_works, (f.name or "").lower()))
    else:
        items.sort(key=lambda f: (-f.n_ut_works, (f.name or "").lower()))
    return FunderSearchResponse(
        items=items[offset : offset + limit], total=len(items), facets=facets
    )


@router.get("/{funder_id}", response_model=FunderDetailResponse)
async def funder_detail(
    funder_id: int,
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
) -> FunderDetailResponse:
    funder = await session.get(JiscFunder, funder_id)
    if funder is None:
        raise HTTPException(status_code=404, detail=f"funder {funder_id} not found")
    year_range = clamped_year_range(institution, year_from, year_to)
    counts = await funders_service.ut_work_counts(session, institution, year_range)
    canon = await funders_service.canon_links(session)
    union_counts = await funders_service.ut_funder_work_counts(
        session, institution, canon.bare_ids, year_range
    )
    ids = canon.bare_ids.get(funder_id, set())
    item = _to_item(funder, sorted(ids), ids, counts, union_counts.get(funder_id, 0))
    # Top journals across every twin the works may cite.
    top: list[dict[str, Any]] = []
    for bare in sorted(ids, key=lambda b: -counts.get(b, 0)):
        top.extend(
            await funders_service.top_journals(session, institution, bare, year_range=year_range)
        )
    seen: set[str] = set()
    deduped = []
    for j in top:
        if j["issn_l"] not in seen:
            seen.add(j["issn_l"])
            deduped.append(j)
    yearly = await funders_service.works_by_year(session, institution, ids, year_range)
    return FunderDetailResponse(
        **item.model_dump(),
        publications_policy=funder.publications_policy,
        data_archiving_policy=funder.data_archiving_policy,
        openaire=canon.openaire.get(funder_id),
        top_journals=[FunderTopJournal(**j) for j in deduped[:5]],
        works_by_year=yearly,
    )
