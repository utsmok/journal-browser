"""/api/v1/{code}/deals: one institution's deal register with journal counts.

The register is exactly the deals the institution participates in (a
deal_institutions row; owner decision 2026-10-23), counted by effective
coverage: the shared sheet list, or the institution's scoped override list
when its relation sets journal_override.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import InstitutionDep
from ..models import Deal, DealJournal, Institution, Publisher
from ..queries import cache_epoch
from ..schemas import DealOut
from ..services.cache import SWR_CACHE, swr_get, swr_put, swr_schedule
from ..services.deal_coverage import DEAL_FIELDS, apc_agg, covered_join

router = APIRouter(prefix="/deals", tags=["deals"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _deal_out(
    deal: Deal, publisher_name: str | None, journal_count: int, apc_euro_total: float, apc_n: int
) -> DealOut:
    return DealOut(
        **{c: getattr(deal, c) for c in DEAL_FIELDS},
        publisher_name=publisher_name,
        journal_count=journal_count,
        apc_euro_total=float(apc_euro_total),
        apc_n=int(apc_n),
    )


@router.get("", response_model=list[DealOut])
async def list_deals(
    session: SessionDep,
    institution: InstitutionDep,
    status: Annotated[str, Query(pattern="^(current|archive|all)$")] = "current",
) -> list[DealOut]:
    swr_key = ("deals_list", institution.id, status)
    epoch = await cache_epoch(session)
    fresh, bundle = swr_get(SWR_CACHE, swr_key, epoch)
    if fresh:
        return bundle
    if bundle is not None:
        swr_schedule(SWR_CACHE, swr_key, _deals_list_factory(institution.id, status))
        return bundle
    epoch, built = await _build_deals_list(session, institution, status)
    swr_put(SWR_CACHE, swr_key, epoch, built)
    return built


def _deals_list_factory(iid: int, status: str):
    async def _factory():
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from ..db import get_engine

        async with async_sessionmaker(get_engine(), expire_on_commit=False)() as session:
            inst = (await session.scalars(select(Institution).where(Institution.id == iid))).one()
            return await _build_deals_list(session, inst, status)

    return _factory


async def _build_deals_list(
    session: AsyncSession, institution: Institution, status: str
) -> tuple[Any, list[DealOut]]:
    covered = covered_join(institution.id)
    apc = apc_agg(institution)
    query = covered(
        select(
            Deal,
            Publisher.name,
            func.count(DealJournal.issn_l.distinct()),
            func.coalesce(apc.c.apc_euro_total, 0),
            func.coalesce(apc.c.apc_n, 0),
        )
        .outerjoin(Publisher, Publisher.id == Deal.publisher_id)
        .outerjoin(apc, apc.c.deal_id == Deal.id)
        .group_by(Deal.id, Publisher.name, apc.c.apc_euro_total, apc.c.apc_n)
    )
    if status != "all":
        query = query.where(Deal.status == status)
    rows = (await session.execute(query)).all()
    return await cache_epoch(session), [
        _deal_out(deal, name, int(count or 0), euro, n) for deal, name, count, euro, n in rows
    ]


@router.get("/{deal_id}", response_model=DealOut)
async def deal_detail(deal_id: int, session: SessionDep, institution: InstitutionDep) -> DealOut:
    covered = covered_join(institution.id)
    apc = apc_agg(institution)
    row = (
        await session.execute(
            covered(
                select(
                    Deal,
                    Publisher.name,
                    func.count(DealJournal.issn_l.distinct()),
                    func.coalesce(apc.c.apc_euro_total, 0),
                    func.coalesce(apc.c.apc_n, 0),
                )
                .outerjoin(Publisher, Publisher.id == Deal.publisher_id)
                .outerjoin(apc, apc.c.deal_id == Deal.id)
                .where(Deal.id == deal_id)
                .group_by(Deal.id, Publisher.name, apc.c.apc_euro_total, apc.c.apc_n)
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="deal not found")
    deal, name, count, euro, n = row
    return _deal_out(deal, name, int(count or 0), euro, n)
