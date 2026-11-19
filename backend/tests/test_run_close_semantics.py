"""Run-closing semantics: a superseded (zombie) run must not flip its
failed row back to completed, must not rewrite harvest_state, and every
closed run must bump cache_epoch because per-page commits may already have
changed serving data.

Regression evidence: production harvest_runs 47/50 and 50/52 (2026-10-26)
are completed rows whose finish landed after a newer same-key run had
started and superseded them, and 31 completed runs after 2026-11-05 15:04
never bumped cache_epoch because they bypass run_harvest.
"""

from datetime import UTC, datetime

from sqlalchemy import select

from journal_browser.ingest import IngestSession
from journal_browser.models import CacheEpoch, HarvestRun, HarvestState


async def _seed_epoch(db) -> None:
    db.add(CacheEpoch(id=1, bumped_at=datetime(1970, 1, 1, tzinfo=UTC)))
    await db.commit()


async def _state_row(db, filter_set: str):
    return (
        await db.execute(
            select(HarvestState).where(
                HarvestState.source == "openalex",
                HarvestState.entity_type == "work",
                HarvestState.filter_set == filter_set,
                HarvestState.institution_id.is_(None),
            )
        )
    ).scalar_one_or_none()


async def test_superseded_run_cannot_close_itself(db):
    await _seed_epoch(db)
    zombie = IngestSession(db)
    await zombie.start_run("openalex", "work", "sweep-a", {})
    await db.commit()

    fresh = IngestSession(db)
    await fresh.start_run("openalex", "work", "sweep-b", {})
    await db.commit()

    zombie_row = await db.get(HarvestRun, zombie.run_id)
    assert zombie_row.status == "failed"
    assert zombie_row.stats["error"].startswith("stale: superseded")

    await zombie.finish_run("completed", {"works": 3})
    await db.commit()

    await db.refresh(zombie_row)
    assert zombie_row.status == "failed", "zombie finish resurrected a superseded run"
    assert zombie_row.stats["error"].startswith("stale: superseded")
    assert await _state_row(db, "sweep-a") is None, "zombie finish wrote harvest_state"

    await fresh.finish_run("completed", {"works": 5})
    await db.commit()
    live = await _state_row(db, "sweep-b")
    assert live is not None and live.last_run_id == fresh.run_id
    assert live.status == "completed"


async def test_finish_run_bumps_cache_epoch_on_completed_and_failed(db):
    await _seed_epoch(db)
    epoch = select(CacheEpoch.bumped_at).where(CacheEpoch.id == 1)

    a = IngestSession(db)
    await a.start_run("openalex", "work", "sweep-a", {})
    await a.finish_run("completed", {"works": 1})
    await db.commit()
    first = (await db.execute(epoch)).scalar_one()
    assert first > datetime(1970, 1, 1, tzinfo=UTC)

    b = IngestSession(db)
    await b.start_run("openalex", "work", "sweep-b", {})
    await b.finish_run("failed", {"error": "see logs"})
    await db.commit()
    second = (await db.execute(epoch)).scalar_one()
    assert second > first, "a failed close must still invalidate caches"
