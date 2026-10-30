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
from ..models import Deal, DealInstitution, DealJournal, Publisher
from ..schemas import DealOut
from ..services.deal_coverage import deal_institution_join, dj_scope

router = APIRouter(prefix="/deals", tags=["deals"])

#: DealOut fields that map 1:1 onto Deal columns (the detail path getattrs
#: them); excludes the computed register extras. Set-equal to the column
#: list, verified against Deal.__table__.columns 2026-10-30.
_DEAL_OUT_EXTRAS = {"publisher_name", "covers_in_group", "journal_count"}
DEAL_FIELDS = [k for k in DealOut.model_fields if k not in _DEAL_OUT_EXTRAS]

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _covered_join(institution_id: int):
    """JOIN clauses: participation row + effective (override-aware) list."""

    def covered(q):
        return (
            q.join(DealInstitution, deal_institution_join(institution_id))
            # LEFT JOIN: a participating deal shows even when its
            # effective journal list is empty (count 0). Admin-excluded
            # journals stay out of counts and membership everywhere.
            .outerjoin(
                DealJournal,
                (DealJournal.deal_id == Deal.id)
                & dj_scope(institution_id)
                & DealJournal.excluded.is_not(True),
            )
        )

    return covered


def _deal_out(deal: Deal, publisher_name: str | None, journal_count: int) -> DealOut:
    return DealOut(
        **{c: getattr(deal, c) for c in DEAL_FIELDS},
        publisher_name=publisher_name,
        journal_count=journal_count,
    )


@router.get("", response_model=list[DealOut])
async def list_deals(
    session: SessionDep,
    institution: InstitutionDep,
    status: Annotated[str, Query(pattern="^(current|archive|all)$")] = "current",
) -> list[DealOut]:
    covered = _covered_join(institution.id)
    query = covered(
        select(Deal, Publisher.name, func.count(DealJournal.issn_l.distinct()))
        .outerjoin(Publisher, Publisher.id == Deal.publisher_id)
        .group_by(Deal.id, Publisher.name)
    )
    if status != "all":
        query = query.where(Deal.status == status)
    rows = (await session.execute(query)).all()
    return [_deal_out(deal, name, int(count or 0)) for deal, name, count in rows]


@router.get("/{deal_id}", response_model=DealOut)
async def deal_detail(deal_id: int, session: SessionDep, institution: InstitutionDep) -> DealOut:
    covered = _covered_join(institution.id)
    row = (
        await session.execute(
            covered(
                select(Deal, Publisher.name, func.count(DealJournal.issn_l.distinct()))
                .outerjoin(Publisher, Publisher.id == Deal.publisher_id)
                .where(Deal.id == deal_id)
                .group_by(Deal.id, Publisher.name)
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="deal not found")
    deal, name, count = row
    return _deal_out(deal, name, int(count or 0))
