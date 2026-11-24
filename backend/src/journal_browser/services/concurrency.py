"""Bounded concurrent query execution across read-only AsyncSessions.

When `session.bind` is an AsyncEngine (production), runs callables
concurrently with up to QUERY_CONCURRENCY pooled sessions. Inside test
savepoint/single-connection fixtures (`AsyncConnection` bind), runs
sequentially on the shared session so uncommitted fixture rows stay
visible and transactions never contend.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any
from weakref import WeakKeyDictionary

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

QUERY_CONCURRENCY = 4

_query_slots: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = WeakKeyDictionary()


def _slots() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    slots = _query_slots.get(loop)
    if slots is None:
        slots = _query_slots.setdefault(loop, asyncio.Semaphore(QUERY_CONCURRENCY))
    return slots


async def together(
    session: AsyncSession,
    queries: Sequence[Callable[[AsyncSession], Awaitable[Any]]],
) -> list[Any]:
    """Run read-only async session callables concurrently when backed by an Engine."""
    if not isinstance(session.bind, AsyncEngine):
        return [await query(session) for query in queries]
    slots = _slots()
    maker = async_sessionmaker(session.bind, expire_on_commit=False)

    async def one(query: Callable[[AsyncSession], Awaitable[Any]]) -> Any:
        async with slots, maker() as own:
            return await query(own)

    return list(await asyncio.gather(*(one(query) for query in queries)))
