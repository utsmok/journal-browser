"""Ops status for admins: wave outcome, schedules, backups, freshness.

GET /admin/ops/status answers the questions that used to need shell
access: did last night's wave finish (from harvest_runs), when do the
scheduled jobs fire next (parsed from the JB_*_CRON environment), how old
is the newest backup archive (stat on JB_BACKUP_DIR), and how fresh is
the served data per source (the same max() queries /meta/freshness uses).
Read-only by design: there is deliberately no "run now" trigger — the
harvests stay shell-only to protect the OpenAlex credit budget.
"""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    ApcEvidence,
    Deal,
    HarvestRun,
    HarvestState,
    InstitutionWorksStats,
    Journal,
    ScimagojrMetric,
)
from ...schemas import AdminOpsStatusOut
from .auth import AdminDep, SessionDep
from .cron_next import next_fire

router = APIRouter(prefix="/admin", tags=["admin"])

# A wave runs its stages back-to-back, but a slow credit-priced stage can
# take hours; gaps up to this size are treated as one wave, a larger gap
# starts a new cluster.
WAVE_STAGE_GAP = timedelta(hours=6)
WAVE_LOOKBACK_DAYS = 8

SCHEDULES = (
    ("refresh_wave", "JB_REFRESH_WAVE_CRON", "30 1 * * *"),
    ("source_wave", "JB_SOURCE_WAVE_CRON", "0 22 * * 0"),
    ("backup", "JB_BACKUP_CRON", "0 4 * * *"),
)

BACKUP_GLOB = "journalbrowser-*.dump"


async def _last_wave_cluster(session: AsyncSession, now: datetime) -> dict[str, Any] | None:
    """Most recent burst of global runs, oldest first.

    Global (institution_id IS NULL) only: the wave's stages are all global
    jobs, and per-institution runs fire on unrelated schedules.
    """
    runs = list(
        (
            await session.scalars(
                select(HarvestRun)
                .where(
                    HarvestRun.institution_id.is_(None),
                    HarvestRun.started_at >= now - timedelta(days=WAVE_LOOKBACK_DAYS),
                )
                .order_by(HarvestRun.started_at.desc())
                .limit(500)
            )
        ).all()
    )
    cluster: list[HarvestRun] = []
    prev_started: datetime | None = None
    for run in runs:
        if prev_started is not None and prev_started - run.started_at > WAVE_STAGE_GAP:
            break
        cluster.append(run)
        prev_started = run.started_at
    if not cluster:
        return None
    seen: set[tuple[str, str]] = set()
    stages = []
    for run in sorted(cluster, key=lambda r: r.started_at):
        key = (run.source, run.entity_type)
        if key in seen:
            continue
        seen.add(key)
        stages.append(
            {
                "source": run.source,
                "entity_type": run.entity_type,
                "status": run.status,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
            }
        )
    finished = [r.finished_at for r in cluster if r.finished_at is not None]
    return {
        "window_start": cluster[-1].started_at,
        "window_end": max(finished) if finished else cluster[0].started_at,
        "stages": stages,
        "failed": sum(1 for r in cluster if r.status == "failed"),
        "running": sum(1 for r in cluster if r.status == "running"),
    }


def _schedules(now: datetime) -> list[dict[str, Any]]:
    entries = []
    for name, env_var, default in SCHEDULES:
        from_env = bool(os.environ.get(env_var, "").strip())
        cron = os.environ.get(env_var, "").strip() or default
        entry: dict[str, Any] = {
            "name": name,
            "cron": cron,
            "from_env": from_env,
            "next_run_utc": None,
            "error": None,
        }
        try:
            entry["next_run_utc"] = next_fire(cron, now)
        except ValueError as exc:
            entry["error"] = str(exc)
        entries.append(entry)
    return entries


def _backup_status() -> dict[str, Any]:
    backup: dict[str, Any] = {
        "available": False,
        "detail": None,
        "file": None,
        "size_bytes": None,
        "modified_at": None,
    }
    # backup.sh writes journalbrowser-<stamp>.dump here in the scheduler
    # container; the backend container only sees it when compose mounts
    # ./backups in (currently it does not, so live reports unavailable).
    backup_dir = Path(os.environ.get("JB_BACKUP_DIR") or "/backups")
    try:
        candidates = sorted(backup_dir.glob(BACKUP_GLOB), key=lambda p: p.stat().st_mtime)
    except OSError as exc:
        backup["detail"] = f"backup directory not readable ({exc.strerror or exc})"
        return backup
    if not candidates:
        backup["detail"] = "no backup archives found"
        return backup
    newest = candidates[-1]
    stat = newest.stat()
    backup.update(
        available=True,
        file=newest.name,
        size_bytes=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime, UTC),
    )
    return backup


async def _freshness(session: AsyncSession) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Per-source harvest freshness plus concrete table timestamps.

    One entry per (source, entity_type): the HarvestState with the newest
    finished_at across institutions — the same population /meta/freshness
    serves, collapsed to instance-global rows for the ops card.
    """
    rows = (
        await session.execute(
            select(
                HarvestState.source,
                HarvestState.entity_type,
                HarvestState.status,
                HarvestRun.finished_at,
            )
            .outerjoin(HarvestRun, HarvestRun.id == HarvestState.last_run_id)
            .order_by(HarvestState.source, HarvestState.entity_type)
        )
    ).all()
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for source, entity_type, status, finished_at in rows:
        key = (source, entity_type)
        rank = (finished_at is not None, finished_at or epoch)
        if key not in best or rank > best[key]["_rank"]:
            best[key] = {
                "_rank": rank,
                "source": source,
                "entity_type": entity_type,
                "status": status,
                "finished_at": finished_at,
            }
    freshness = [{k: v for k, v in entry.items() if k != "_rank"} for entry in best.values()]

    async def _max_ts(stmt):
        return await session.scalar(stmt)

    tables = {
        "journals": await _max_ts(select(func.max(Journal.harvested_at))),
        "doaj": await _max_ts(select(func.max(Journal.doaj_harvested_at))),
        "deals": await _max_ts(select(func.max(Deal.updated_at))),
        "institution_works_stats": await _max_ts(
            select(func.max(InstitutionWorksStats.updated_at))
        ),
        "scimagojr_metrics": await _max_ts(select(func.max(ScimagojrMetric.year))),
        "apc_evidence": await _max_ts(select(func.max(ApcEvidence.period))),
    }
    return freshness, tables


@router.get("/ops/status", response_model=AdminOpsStatusOut)
async def ops_status(session: SessionDep, _: AdminDep) -> dict[str, Any]:
    now = datetime.now(UTC)
    freshness, tables = await _freshness(session)
    return {
        "generated_at": now,
        "last_wave": await _last_wave_cluster(session, now),
        "schedules": _schedules(now),
        "backup": _backup_status(),
        "freshness": freshness,
        "tables": tables,
    }
