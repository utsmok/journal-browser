"""/api/v1/deals: open publishing deals with journal counts."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Deal, DealInstitution, DealJournal, Publisher
from ..routers.journals import DEAL_FIELDS, HOME_INST
from ..schemas import DealOut

router = APIRouter(prefix="/deals", tags=["deals"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _deal_out(
    deal: Deal, publisher_name: str | None, journal_count: int, twente_relevant: bool
) -> DealOut:
    return DealOut(
        **{c: getattr(deal, c) for c in DEAL_FIELDS},
        publisher_name=publisher_name,
        journal_count=journal_count,
        twente_relevant=twente_relevant,
    )


async def _twente_deal_ids(session: AsyncSession) -> set[int]:
    rows = await session.execute(
        select(DealInstitution.deal_id).where(DealInstitution.institution_id == HOME_INST)
    )
    return set(rows.scalars().all())


@router.get("", response_model=list[DealOut])
async def list_deals(
    session: SessionDep,
    status: Annotated[str, Query(pattern="^(current|archive|all)$")] = "current",
    scope: Annotated[str, Query(pattern="^(home|all)$")] = "home",
) -> list[DealOut]:
    query = (
        select(Deal, Publisher.name, func.count(DealJournal.issn_l))
        .outerjoin(Publisher, Publisher.id == Deal.publisher_id)
        .outerjoin(DealJournal, DealJournal.deal_id == Deal.id)
        .group_by(Deal.id, Publisher.name)
    )
    if status != "all":
        query = query.where(Deal.status == status)
    relevant_ids = await _twente_deal_ids(session)
    if scope == "home":
        query = query.where(Deal.id.in_(relevant_ids or {-1}))
    rows = (await session.execute(query)).all()
    return [
        _deal_out(deal, name, int(count or 0), deal.id in relevant_ids)
        for deal, name, count in rows
    ]


@router.get("/{deal_id}", response_model=DealOut)
async def deal_detail(deal_id: int, session: SessionDep) -> DealOut:
    row = (
        await session.execute(
            select(Deal, Publisher.name, func.count(DealJournal.issn_l))
            .outerjoin(Publisher, Publisher.id == Deal.publisher_id)
            .outerjoin(DealJournal, DealJournal.deal_id == Deal.id)
            .where(Deal.id == deal_id)
            .group_by(Deal.id, Publisher.name)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="deal not found")
    deal, name, count = row
    relevant_ids = await _twente_deal_ids(session)
    return _deal_out(deal, name, int(count or 0), deal.id in relevant_ids)
