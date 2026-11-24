"""Orphaned-run reaper: a 'running' row whose process is gone is failed with
a reason; a run whose process still holds its lock is left alone.

Regression evidence: harvest_runs 408 (2026-11-22) stayed 'running' with
empty stats after a redeploy killed the scheduler mid-wave.
"""

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from journal_browser import runlocks
from journal_browser.ingest import IngestSession, reap_orphaned_runs
from journal_browser.models import CacheEpoch, HarvestRun

# Another process holding a run lock, as a job in another container would.
HOLD_LOCK = """
import fcntl, sys, time
with open(sys.argv[1], "w") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    sys.stdout.write("locked\\n")
    sys.stdout.flush()
    time.sleep(120)
"""


@pytest.fixture
def lock_dir(tmp_path, monkeypatch):
    """Run locks in a per-test dir instead of the landing dir."""

    def path(run_id: int) -> Path:
        return tmp_path / f"{run_id}.lock"

    monkeypatch.setattr(runlocks, "run_lock_path", path)
    return tmp_path


async def _dead_run(db) -> HarvestRun:
    """A 'running' row whose process died before liveness locks existed."""
    row = HarvestRun(
        source="openalex", entity_type="work", status="running", config_fingerprint="f", stats={}
    )
    db.add(row)
    await db.commit()
    return row


async def test_row_without_live_owner_is_failed_with_reason(db, lock_dir):
    row = await _dead_run(db)

    reaped = await reap_orphaned_runs(db)
    await db.commit()
    await db.refresh(row)

    assert [run.id for run in reaped] == [row.id]
    assert row.status == "failed"
    assert row.finished_at is not None
    assert row.stats["error"].startswith("orphaned: process gone at ")


async def test_reaper_bumps_cache_epoch_like_any_close(db, lock_dir):
    db.add(CacheEpoch(id=1, bumped_at=datetime(1970, 1, 1, tzinfo=UTC)))
    await db.commit()
    await _dead_run(db)

    await reap_orphaned_runs(db)
    await db.commit()

    epoch = (await db.get(CacheEpoch, 1)).bumped_at
    assert epoch > datetime(1970, 1, 1, tzinfo=UTC)


async def test_run_held_by_its_process_stays_running(db, lock_dir):
    live = IngestSession(db)
    await live.start_run("openalex", "work", "sweep", {})
    await db.commit()
    assert (lock_dir / f"{live.run_id}.lock").exists()

    assert await reap_orphaned_runs(db) == []

    row = await db.get(HarvestRun, live.run_id)
    assert row.status == "running" and row.finished_at is None


async def test_finished_run_removes_its_lock_file(db, lock_dir):
    live = IngestSession(db)
    await live.start_run("openalex", "work", "sweep", {})

    await live.finish_run("completed", {})
    await db.commit()

    assert not (lock_dir / f"{live.run_id}.lock").exists()


async def test_abandoned_session_lets_go_of_its_lock(db, lock_dir):
    """A job that drops its session without finish_run() must not keep its
    run looking alive for as long as the process lives."""
    abandoned = IngestSession(db)
    await abandoned.start_run("openalex", "work", "sweep", {})
    await db.commit()
    run_id = abandoned.run_id
    del abandoned

    assert not (lock_dir / f"{run_id}.lock").exists()
    assert [run.id for run in await reap_orphaned_runs(db)] == [run_id]


async def test_lock_held_by_another_process_keeps_run_running_until_it_dies(db, lock_dir):
    row = await _dead_run(db)
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLD_LOCK, str(lock_dir / f"{row.id}.lock")],
        stdout=subprocess.PIPE,
    )
    try:
        assert holder.stdout is not None and holder.stdout.readline() == b"locked\n"

        assert await reap_orphaned_runs(db) == []
    finally:
        holder.kill()
        holder.wait()

    # The kernel dropped the lock with the process: now it is an orphan.
    assert [run.id for run in await reap_orphaned_runs(db)] == [row.id]


async def test_leftover_lock_file_of_a_dead_owner_is_reaped_and_removed(db, lock_dir):
    row = await _dead_run(db)
    stale = lock_dir / f"{row.id}.lock"
    stale.write_text("")

    assert [run.id for run in await reap_orphaned_runs(db)] == [row.id]
    assert not stale.exists()


async def test_only_running_rows_are_touched(db, lock_dir):
    done = HarvestRun(
        source="jct",
        entity_type="deal",
        status="completed",
        config_fingerprint="f",
        stats={"deals": 3},
    )
    db.add(done)
    await db.commit()
    await _dead_run(db)

    reaped = await reap_orphaned_runs(db)
    await db.commit()

    assert [run.id for run in reaped] != [done.id]
    await db.refresh(done)
    assert done.status == "completed" and done.stats == {"deals": 3}


@pytest.mark.skipif(os.geteuid() == 0, reason="root opens any file, so the lock is readable")
async def test_unreadable_lock_is_never_reaped(db, lock_dir):
    row = await _dead_run(db)
    stale = lock_dir / f"{row.id}.lock"
    stale.write_text("")
    stale.chmod(0o000)
    try:
        assert runlocks.run_lock_state(row.id) is runlocks.LockState.UNKNOWN
        assert await reap_orphaned_runs(db) == []
    finally:
        stale.chmod(0o644)
