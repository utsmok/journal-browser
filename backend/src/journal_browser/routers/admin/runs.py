from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import desc, func, select

from ...models import Deal, DealJournal, HarvestRun, Institution, Publisher
from ...schemas import AdminRunOut, FlaggedDealOut
from .auth import AdminDep, SessionDep
from .settings_admin import _get_institution_or_404

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/runs", response_model=list[AdminRunOut])
async def list_runs(
    session: SessionDep,
    _: AdminDep,
    institution: Annotated[str | None, Query(max_length=32)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, Any]]:
    query = (
        select(HarvestRun, Institution.code)
        .outerjoin(Institution, Institution.id == HarvestRun.institution_id)
        .order_by(desc(HarvestRun.id))
        .limit(limit)
    )
    if institution is not None:
        inst = await _get_institution_or_404(session, institution)
        query = query.where(HarvestRun.institution_id == inst.id)
    rows = (await session.execute(query)).all()
    return [
        {
            "id": r.id,
            "source": r.source,
            "entity_type": r.entity_type,
            "institution_id": r.institution_id,
            "institution_code": code,
            "status": r.status,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
            "stats": r.stats,
        }
        for r, code in rows
    ]


@router.get("/flagged", response_model=list[FlaggedDealOut])
async def flagged_deals(session: SessionDep, _: AdminDep) -> list[dict[str, Any]]:
    journal_count = (
        select(func.count())
        .select_from(DealJournal)
        .where(DealJournal.deal_id == Deal.id)
        .correlate(Deal)
        .scalar_subquery()
    )
    rows = (
        await session.execute(
            select(Deal, Publisher.name, journal_count)
            .join(Publisher, Publisher.id == Deal.publisher_id)
            .where(Deal.needs_curation.is_(True))
            .order_by(Deal.status.desc(), Publisher.name)
        )
    ).all()
    return [
        {
            "id": deal.id,
            "publisher": name,
            "esac_id": deal.esac_id,
            "status": deal.status,
            "duration": deal.duration_text,
            "journals": count,
            "reason": deal.needs_curation_reason,
        }
        for deal, name, count in rows
    ]
