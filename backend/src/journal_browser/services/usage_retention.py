"""Usage IP retention: null raw client IPs after the retention window.

The nightly loop lives in main.py's lifespan; this module is just the one
SQL statement so it stays directly testable. Rows and country columns
survive — only the raw IP is forgotten.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def prune_old_ips(session: AsyncSession, days: int) -> int:
    """Null `ip` on usage events older than `days`; returns rows changed."""
    result = await session.execute(
        text(
            "UPDATE usage_events SET ip = NULL "
            "WHERE ip IS NOT NULL AND ts < now() - make_interval(days => :days)"
        ),
        {"days": days},
    )
    await session.commit()
    return result.rowcount
