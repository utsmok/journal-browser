"""/api/v1/meta: limitations registry + freshness metadata."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import InstitutionDep
from ..models import HarvestRun, HarvestState, Limitation
from ..schemas import DegradedSource, FreshnessEntry, FreshnessResponse, LimitationOut
from ..services import source_health
from ..services.freshness import data_updated_at, source_freshness

router = APIRouter(prefix="/meta", tags=["meta"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/limitations", response_model=list[LimitationOut])
async def list_limitations(
    session: SessionDep,
    institution: InstitutionDep,
    source: Annotated[str | None, Query(max_length=50)] = None,
) -> list[LimitationOut]:
    query = select(Limitation).order_by(Limitation.source, Limitation.code)
    if source:
        query = query.where(Limitation.source == source)
    rows = list((await session.execute(query)).scalars().all())
    # The registry is global but windows are per institution: hints written
    # with the {window_start} placeholder render this institution's year.
    # Served as dicts: rewriting row.hint on the session-persistent
    # instances would flush the substitution into the canon table on any
    # later query in the request.
    window = str(institution.data_window_start or 2020)
    return [
        {c.name: getattr(row, c.name) for c in Limitation.__table__.columns}
        | {"hint": row.hint.replace("{window_start}", window)}
        for row in rows
    ]


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

    sources = await source_freshness(session, [institution], public_only=True)
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
        sources=sources,
        data_updated_at=data_updated_at(sources),
        degraded=[
            DegradedSource(
                source=entry["source"],
                detail=entry["detail"],
                since=datetime.fromtimestamp(entry["since"], tz=UTC),
            )
            for entry in source_health.snapshot()
        ],
    )
