"""Fail harvest runs whose process is gone (see ingest.reap_orphaned_runs).

The scheduler runs this at start and both waves run it before their first
stage, so a wave killed by a container recreate or an OOM kill no longer
leaves rows 'running' forever. Prints one line per reaped run; the shell
wrapper (scripts/lib.sh, reap_orphans) turns that into an alert.

Usage: uv run python jobs/reap_orphaned_runs.py
"""

from sqlalchemy.ext.asyncio import AsyncSession

from journal_browser.ingest import reap_orphaned_runs
from journal_browser.jobrunner import run_job


async def main(session: AsyncSession, limit: int | None) -> None:
    for run in await reap_orphaned_runs(session):
        print(
            f"run {run.id} {run.source}/{run.entity_type} "
            f"institution={run.institution_id} started {run.started_at:%Y-%m-%dT%H:%M:%SZ}"
        )
    await session.commit()


if __name__ == "__main__":
    run_job(main)
