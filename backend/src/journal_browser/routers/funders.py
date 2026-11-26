"""/api/v1/{code}/funders: Jisc OPF funder picker + policy detail.

Funders are canon (not institution-scoped); only the UT-work attribution
is per institution. work_funders (migration 0049) may be absent — the
counts degrade to zeros instead of erroring."""

from collections.abc import Collection
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import InstitutionDep
from ..identifiers import (
    REQUIREMENT_ORDER,
    normalize_policy_requirements,
    normalize_requirement,
)
from ..models import Institution, JiscFunder
from ..queries import cache_epoch
from ..schemas import (
    FunderDetailResponse,
    FunderListItem,
    FunderSearchResponse,
    FunderTopJournal,
)
from ..services import funders as funders_service
from ..services.cache import SWR_CACHE, swr_get, swr_put, swr_schedule
from ..services.works_query import clamped_year_range
from .params import split_multi

router = APIRouter(prefix="/funders", tags=["funders"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

DEFAULT_LIMIT = 25


def _norm_req(block: Any) -> str | None:
    """Requirement level of one policy sub-block, in canonical spelling
    (rows normalized before the Jisc misspelling was mapped still carry it)."""
    if not isinstance(block, dict):
        return None
    return normalize_requirement(block.get("requirement"))


def _req_filter(raw: str | None) -> set[str]:
    """Requirement levels of one multi-value filter, in canonical spelling."""
    return {req for v in (split_multi(raw) or []) if (req := normalize_requirement(v))}


def _to_item(
    funder: JiscFunder,
    ids: set[str],
    counts: dict[str, int],
    n_ut_works: int,
    whole_ids: Collection[str] | None = None,
) -> FunderListItem:
    pub_policy = funder.publications_policy if isinstance(funder.publications_policy, dict) else {}
    data_policy = (
        funder.data_archiving_policy if isinstance(funder.data_archiving_policy, dict) else {}
    )
    structured = bool(pub_policy.get("archiving_policy"))
    # Link to the twin that stands for the funder itself where programme
    # records share its twins; elsewhere to the twin the works cite most,
    # ties to the lowest id. Bare ids everywhere. n_ut_works is the
    # twin-set-deduped count from ut_funder_work_counts: one work
    # crediting two twins of the same funder counts once.
    openalex_id = max(sorted(whole_ids or ids), key=lambda bare: counts.get(bare, 0), default=None)
    return FunderListItem(
        id=funder.id,
        name=funder.name,
        country=funder.country,
        url=funder.url,
        ror=funder.ror,
        fundref=funder.fundref,
        openalex_funder_id=openalex_id,
        policy_structured=structured,
        oa_publishing_req=_norm_req(pub_policy.get("publishing_policy")),
        green_archiving_req=_norm_req(pub_policy.get("archiving_policy")),
        data_policy_req=_norm_req(data_policy),
        n_ut_works=n_ut_works,
    )


@router.get("", response_model=FunderSearchResponse)
async def search_funders(
    session: SessionDep,
    institution: InstitutionDep,
    q: Annotated[str | None, Query(max_length=200)] = None,
    country: Annotated[str | None, Query(max_length=200)] = None,
    policy_structured: bool | None = None,
    has_works: bool | None = None,
    oa_publishing: Annotated[str | None, Query(max_length=200)] = None,
    green_archiving: Annotated[str | None, Query(max_length=200)] = None,
    data_policy: Annotated[str | None, Query(max_length=200)] = None,
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
                canon.bare_ids.get(funder.id, set()),
                counts,
                union_counts.get(funder.id, 0),
                canon.whole_ids.get(funder.id),
            )
        )

    countries = {c.strip().upper() for c in (split_multi(country) or []) if c.strip()}
    oa_pub_reqs = _req_filter(oa_publishing)
    green_reqs = _req_filter(green_archiving)
    data_reqs = _req_filter(data_policy)

    def _matches(
        item: FunderListItem,
        *,
        skip: str | None = None,
    ) -> bool:
        if skip != "country" and countries and (item.country or "").upper() not in countries:
            return False
        if (
            skip != "policy_structured"
            and policy_structured is not None
            and item.policy_structured != policy_structured
        ):
            return False
        if skip != "has_works" and has_works is not None and (item.n_ut_works > 0) != has_works:
            return False
        if (
            skip != "oa_publishing"
            and oa_pub_reqs
            and (item.oa_publishing_req or "none") not in oa_pub_reqs
        ):
            return False
        if (
            skip != "green_archiving"
            and green_reqs
            and (item.green_archiving_req or "none") not in green_reqs
        ):
            return False
        return not (
            skip != "data_policy"
            and data_reqs
            and (item.data_policy_req or "none") not in data_reqs
        )

    # Drop-own-dimension facets over the query-matched base.
    country_counts: dict[str, int] = {}
    policy_counts = {"true": 0, "false": 0}
    has_works_counts = {"true": 0, "false": 0}
    oa_pub_counts: dict[str, int] = {}
    green_counts: dict[str, int] = {}
    data_counts: dict[str, int] = {}

    for item in base_items:
        if _matches(item, skip="country"):
            code = (item.country or "").strip().upper()
            if code:
                country_counts[code] = country_counts.get(code, 0) + 1
        if _matches(item, skip="policy_structured"):
            policy_counts["true" if item.policy_structured else "false"] += 1
        if _matches(item, skip="has_works"):
            has_works_counts["true" if item.n_ut_works > 0 else "false"] += 1
        if _matches(item, skip="oa_publishing"):
            key = item.oa_publishing_req or "none"
            oa_pub_counts[key] = oa_pub_counts.get(key, 0) + 1
        if _matches(item, skip="green_archiving"):
            key = item.green_archiving_req or "none"
            green_counts[key] = green_counts.get(key, 0) + 1
        if _matches(item, skip="data_policy"):
            key = item.data_policy_req or "none"
            data_counts[key] = data_counts.get(key, 0) + 1

    def _ordered_req(counts_map: dict[str, int]) -> dict[str, int]:
        ranked = {k: counts_map[k] for k in REQUIREMENT_ORDER if k in counts_map}
        for k, v in sorted(counts_map.items()):
            if k not in ranked:
                ranked[k] = v
        return ranked

    facets: dict[str, dict[str, int]] = {
        "country": dict(sorted(country_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "policy_structured": policy_counts,
        "has_works": has_works_counts,
        "oa_publishing": _ordered_req(oa_pub_counts),
        "green_archiving": _ordered_req(green_counts),
        "data_policy": _ordered_req(data_counts),
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
    year_range = clamped_year_range(institution, year_from, year_to)
    swr_key = ("funder_detail", institution.id, funder_id, year_range)
    epoch = await cache_epoch(session)
    fresh, bundle = swr_get(SWR_CACHE, swr_key, epoch)
    if fresh:
        return bundle
    if bundle is not None:
        swr_schedule(
            SWR_CACHE, swr_key, _funder_detail_factory(institution.id, funder_id, year_range)
        )
        return bundle
    epoch, built = await _build_funder_detail(session, institution, funder_id, year_range)
    if built is None:
        raise HTTPException(status_code=404, detail=f"funder {funder_id} not found")
    swr_put(SWR_CACHE, swr_key, epoch, built)
    return built


def _funder_detail_factory(iid: int, funder_id: int, year_range: tuple[int, int] | None):
    async def _factory():
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from ..db import get_engine

        async with async_sessionmaker(get_engine(), expire_on_commit=False)() as session:
            inst = (await session.scalars(select(Institution).where(Institution.id == iid))).one()
            return await _build_funder_detail(session, inst, funder_id, year_range)

    return _factory


async def _build_funder_detail(
    session: AsyncSession,
    institution: Institution,
    funder_id: int,
    year_range: tuple[int, int] | None,
) -> tuple[Any, FunderDetailResponse | None]:
    funder = await session.get(JiscFunder, funder_id)
    if funder is None:
        return await cache_epoch(session), None
    counts = await funders_service.ut_work_counts(session, institution, year_range)
    canon = await funders_service.canon_links(session)
    union_counts = await funders_service.ut_funder_work_counts(
        session, institution, canon.bare_ids, year_range
    )
    ids = canon.bare_ids.get(funder_id, set())
    item = _to_item(
        funder, ids, counts, union_counts.get(funder_id, 0), canon.whole_ids.get(funder_id)
    )
    # Top journals across every twin the works may cite (one distinct-work query).
    top = await funders_service.top_journals(
        session, institution, ids, limit=25, year_range=year_range
    )
    yearly = await funders_service.works_by_year(session, institution, ids, year_range)
    return await cache_epoch(session), FunderDetailResponse(
        **item.model_dump(),
        publications_policy=normalize_policy_requirements(funder.publications_policy),
        data_archiving_policy=normalize_policy_requirements(funder.data_archiving_policy),
        openaire=canon.openaire.get(funder_id),
        top_journals=[FunderTopJournal(**j) for j in top],
        works_by_year=yearly,
    )
