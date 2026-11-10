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
from ..models import ApcEvidence, Deal, DealInstitution, DealJournal, Publisher, Work
from ..schemas import DealOut
from ..services.deal_coverage import deal_institution_join, dj_scope
from ..services.works_query import work_type_not_excluded

router = APIRouter(prefix="/deals", tags=["deals"])

#: DealOut fields that map 1:1 onto Deal columns (the detail path getattrs
#: them); excludes the computed register extras. Set-equal to the column
#: list, verified against Deal.__table__.columns 2026-10-30.
_DEAL_OUT_EXTRAS = {"publisher_name", "covers_in_group", "journal_count", "apc_euro_total", "apc_n"}
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


def _apc_agg(institution_id: int):
    """Per-deal APC spend subquery: the institution's works in the deal's
    effective journal list, latest-period evidence per DOI (mirror of the
    orgunit APC aggregation)."""
    # djs needs this institution's participation row in scope: dj_scope
    # reads its journal_override to pick shared vs scoped rows.
    djs = (
        select(DealJournal.deal_id, DealJournal.issn_l)
        .select_from(DealJournal)
        .join(
            DealInstitution,
            (DealInstitution.deal_id == DealJournal.deal_id)
            & (DealInstitution.institution_id == institution_id),
        )
        .where(dj_scope(institution_id), DealJournal.excluded.is_not(True))
        .subquery()
    )
    ranked = (
        select(
            djs.c.deal_id,
            ApcEvidence.euro.label("euro"),
            func.row_number()
            .over(
                partition_by=(djs.c.deal_id, ApcEvidence.doi),
                order_by=(ApcEvidence.period.desc().nulls_last(), ApcEvidence.id.desc()),
            )
            .label("rn"),
        )
        .select_from(djs)
        .join(
            Work,
            (Work.institution_id == institution_id)
            & (Work.journal_issn_l == djs.c.issn_l)
            & Work.doi_normalized.is_not(None)
            # APC euros match works, so the matched set must describe the
            # same population as every other works count.
            & work_type_not_excluded(Work.work_type),
        )
        .join(
            ApcEvidence,
            (ApcEvidence.institution_id == institution_id)
            & (ApcEvidence.doi == Work.doi_normalized),
        )
        .subquery()
    )
    return (
        select(
            ranked.c.deal_id,
            func.coalesce(func.sum(ranked.c.euro), 0).label("apc_euro_total"),
            func.count(ranked.c.euro).label("apc_n"),
        )
        .where(ranked.c.rn == 1)
        .group_by(ranked.c.deal_id)
        .subquery()
    )


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
    covered = _covered_join(institution.id)
    apc = _apc_agg(institution.id)
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
    return [_deal_out(deal, name, int(count or 0), euro, n) for deal, name, count, euro, n in rows]


@router.get("/{deal_id}", response_model=DealOut)
async def deal_detail(deal_id: int, session: SessionDep, institution: InstitutionDep) -> DealOut:
    covered = _covered_join(institution.id)
    apc = _apc_agg(institution.id)
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
