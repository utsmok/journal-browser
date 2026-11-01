from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import desc, func, select

from ...models import (
    AuthorIdentity,
    Deal,
    DealJournal,
    Feedback,
    HarvestRun,
    Institution,
    Publisher,
    WorkIdentity,
)
from ...schemas import AdminRunOut, AdminSummaryOut, FlaggedDealOut
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


@router.get("/summary", response_model=AdminSummaryOut)
async def admin_summary(session: SessionDep, _: AdminDep) -> dict[str, Any]:
    """Counters for the admin dashboard: pipeline health and open work.

    One cheap set of aggregate queries so the overview page needs one call
    instead of four list fetches.
    """
    since = datetime.now(UTC) - timedelta(hours=24)
    failed_24h = await session.scalar(
        select(func.count())
        .select_from(HarvestRun)
        .where(HarvestRun.status == "failed", HarvestRun.started_at >= since)
    )
    running = await session.scalar(
        select(func.count()).select_from(HarvestRun).where(HarvestRun.status == "running")
    )
    flagged = await session.scalar(
        select(func.count()).select_from(Deal).where(Deal.needs_curation.is_(True))
    )
    open_feedback = await session.scalar(
        select(func.count())
        .select_from(Feedback)
        .where(Feedback.status.in_(("todo", "in_progress")))
    )
    author_candidates = await session.scalar(
        select(func.count()).select_from(AuthorIdentity).where(AuthorIdentity.status == "candidate")
    )
    work_candidates = await session.scalar(
        select(func.count()).select_from(WorkIdentity).where(WorkIdentity.status == "candidate")
    )
    last_row = (
        await session.execute(
            select(HarvestRun, Institution.code)
            .outerjoin(Institution, Institution.id == HarvestRun.institution_id)
            .order_by(desc(HarvestRun.id))
            .limit(1)
        )
    ).first()
    last_run = None
    if last_row is not None:
        run, code = last_row
        last_run = {
            "id": run.id,
            "source": run.source,
            "entity_type": run.entity_type,
            "institution_id": run.institution_id,
            "institution_code": code,
            "status": run.status,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
        }
    return {
        "failed_runs_24h": failed_24h or 0,
        "running_runs": running or 0,
        "flagged_deals": flagged or 0,
        "open_feedback": open_feedback or 0,
        "author_identity_candidates": author_candidates or 0,
        "work_identity_candidates": work_candidates or 0,
        "last_run": last_run,
    }
