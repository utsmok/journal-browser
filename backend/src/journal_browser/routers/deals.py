"""/api/v1/{code}/deals: one institution's deal register with journal counts.

The register is exactly the deals the institution participates in (a
deal_institutions row; owner decision 2026-10-23), counted by effective
coverage: the shared sheet list, or the institution's scoped override list
when its relation sets journal_override.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import InstitutionDep
from ..models import Deal, DealJournal, Publisher
from ..schemas import DealOut
from ..services.deal_coverage import apc_agg, covered_join
from ..services.deals import deal_out, deals_list

router = APIRouter(prefix="/deals", tags=["deals"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[DealOut])
async def list_deals(
    session: SessionDep,
    institution: InstitutionDep,
    status: Annotated[str, Query(pattern="^(current|archive|all)$")] = "current",
) -> list[DealOut]:
    return await deals_list(session, institution, status)


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
    return deal_out(deal, name, int(count or 0), euro, n)
