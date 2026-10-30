"""Background recompute of deal-coverage flags after admin deal writes.

Runs on a fresh engine/connection, deliberately outside the request session.
"""

import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ..config import get_settings
from ..harvest.common import get_active_institutions
from ..harvest.denorm import refresh_deal_flags
from .source_health import record_degraded


async def _refresh_deal_flags_soon() -> None:
    """Recompute hosted institutions' coverage on a fresh connection."""
    engine = create_async_engine(get_settings().database_url)
    try:
        maker = async_sessionmaker(engine)
        async with maker() as session:
            hosted = await get_active_institutions(session)
            for inst in hosted:
                await refresh_deal_flags(session, inst.id)
            await session.commit()
    finally:
        await engine.dispose()


_flags_task: asyncio.Task | None = None
_flags_rerun = False


def _schedule_flags_refresh() -> None:
    """Deal writes change per-institution coverage, but the full recompute
    takes tens of seconds on live data — run it in the background so admin
    edits return instantly. Coverage lags the write by about that long."""
    global _flags_task, _flags_rerun
    if _flags_task is not None and not _flags_task.done():
        # A pass is running; it may miss this commit, so run once more after.
        _flags_rerun = True
        return
    _flags_task = asyncio.create_task(_flags_refresh_loop())


async def _flags_refresh_loop() -> None:
    global _flags_rerun
    while True:
        _flags_rerun = False
        try:
            await _refresh_deal_flags_soon()
        except Exception:  # noqa: BLE001 - background job; log and stop
            import logging

            logging.getLogger("journal_browser.admin").exception(
                "background deal-flags refresh failed"
            )
            record_degraded("deal-flags", "background refresh failed")
            return
        if not _flags_rerun:
            return
