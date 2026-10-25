"""/api/v1/meta: limitations registry + freshness metadata."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..models import (
    ApcEvidence,
    Deal,
    HarvestRun,
    HarvestState,
    InstitutionWorksStats,
    Journal,
    Limitation,
    ScimagojrMetric,
)
from ..schemas import FreshnessEntry, FreshnessResponse, LimitationOut

router = APIRouter(prefix="/meta", tags=["meta"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/limitations", response_model=list[LimitationOut])
async def list_limitations(
    session: SessionDep,
    source: Annotated[str | None, Query(max_length=50)] = None,
) -> list[LimitationOut]:
    query = select(Limitation).order_by(Limitation.source, Limitation.code)
    if source:
        query = query.where(Limitation.source == source)
    return list((await session.execute(query)).scalars().all())


@router.get("/freshness", response_model=FreshnessResponse)
async def freshness(session: SessionDep) -> FreshnessResponse:
    settings = get_settings()
    harvests = list(
        (
            await session.execute(
                select(HarvestState, HarvestRun.finished_at)
                .outerjoin(HarvestRun, HarvestRun.id == HarvestState.last_run_id)
                .order_by(HarvestState.source, HarvestState.entity_type)
            )
        ).all()
    )

    async def table_ts(stmt) -> datetime | None:  # noqa: ANN202
        return await session.scalar(stmt)

    tables = {
        "journals": await table_ts(select(func.max(Journal.harvested_at))),
        "deals": await table_ts(select(func.max(Deal.updated_at))),
        "institution_works_stats": await table_ts(
            select(func.max(InstitutionWorksStats.updated_at))
        ),
        "scimagojr_metrics": await table_ts(select(func.max(ScimagojrMetric.year))),
        "apc_evidence": await table_ts(select(func.max(ApcEvidence.period))),
    }
    return FreshnessResponse(
        institution=settings.institution_name,
        institution_short=settings.institution_short,
        ror=settings.institution_ror,
        library_url=settings.library_url,
        oa_guide_url=settings.oa_guide_url,
        support_email=settings.support_email,
        admin_contact=settings.admin_contact,
        research_portal_url=settings.research_portal_url,
        harvests=[
            FreshnessEntry(
                source=state.source,
                entity_type=state.entity_type,
                filter_set=state.filter_set,
                status=state.status,
                finished_at=finished_at,
                stats=state.stats,
            )
            for state, finished_at in harvests
        ],
        tables={k: v for k, v in tables.items()},
    )
