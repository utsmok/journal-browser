"""/api/v1/deals: the Twente deal register with journal counts.

The register is exactly the owner-verified deals carrying a home
deal_institutions link (owner decision 2026-10-23); nothing auto-writes
deals, so every row here was placed by a curation job.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Deal, DealJournal, Publisher
from ..routers.journals import DEAL_FIELDS
from ..schemas import DealOut

router = APIRouter(prefix="/deals", tags=["deals"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _deal_out(deal: Deal, publisher_name: str | None, journal_count: int) -> DealOut:
    return DealOut(
        **{c: getattr(deal, c) for c in DEAL_FIELDS},
        publisher_name=publisher_name,
        journal_count=journal_count,
    )


@router.get("", response_model=list[DealOut])
async def list_deals(
    session: SessionDep,
    status: Annotated[str, Query(pattern="^(current|archive|all)$")] = "current",
) -> list[DealOut]:
    query = (
        select(Deal, Publisher.name, func.count(DealJournal.issn_l))
        .outerjoin(Publisher, Publisher.id == Deal.publisher_id)
        .outerjoin(DealJournal, DealJournal.deal_id == Deal.id)
        .group_by(Deal.id, Publisher.name)
    )
    if status != "all":
        query = query.where(Deal.status == status)
    rows = (await session.execute(query)).all()
    return [_deal_out(deal, name, int(count or 0)) for deal, name, count in rows]


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
    return _deal_out(deal, name, int(count or 0))
