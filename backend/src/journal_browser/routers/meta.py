"""/api/v1/meta: limitations registry + freshness metadata."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
from ..routers.institutions import InstitutionDep
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
async def freshness(session: SessionDep, institution: InstitutionDep) -> FreshnessResponse:
    harvests = list(
        (
            await session.execute(
                select(HarvestState, HarvestRun.finished_at)
                .outerjoin(HarvestRun, HarvestRun.id == HarvestState.last_run_id)
                # This institution's states plus the shared global layer.
                .where(
                    (HarvestState.institution_id == institution.id)
                    | (HarvestState.institution_id.is_(None))
                )
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
        institution=institution.name,
        institution_short=institution.short_name,
        ror=institution.ror,
        library_url=institution.library_url,
        oa_guide_url=institution.oa_guide_url,
        support_email=institution.support_email,
        admin_contact=institution.admin_contact,
        research_portal_url=institution.research_portal_url,
        data_window_start=institution.data_window_start,
        data_window_end=institution.data_window_end,
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
