"""Monotonic-TTL caches shared by search facets and the publisher/unit
snapshots. A harvest bump (cache_epoch in the key) invalidates sooner
than the TTL."""

import asyncio
import logging
import time
from typing import Any

#: Snapshot lifetime in seconds; a harvest bump invalidates sooner.
SNAPSHOT_TTL = 86400

#: Bounded LRU-style caps so long-running processes stay flat in RAM.
SWR_MAX_ENTRIES = 512
FACET_MAX_ENTRIES = 512
SNAPSHOT_MAX_ENTRIES = 256

# Stores live here so the TTL/get/put pattern has exactly one home.
FACET_CACHE: dict[tuple, tuple[float, Any]] = {}
SNAPSHOT_CACHE: dict[tuple, tuple[float, Any]] = {}

logger = logging.getLogger(__name__)

# Stale-while-revalidate detail bundles: key -> (epoch, bundle). A
# harvest bump changes cache_epoch, which invalidates every epoch-keyed
# cache at once; without SWR each detail page pays its full cold build
# right after every harvest wave (60+ s under load). SWR serves the
# previous epoch's bundle immediately and rebuilds in the background, so
# visitors never wait on a rebuild they did not cause.
SWR_CACHE: dict[tuple, tuple[Any, Any]] = {}
_rebuilding: set[tuple] = set()
_rebuild_tasks: set[asyncio.Task] = set()


def _touch_and_evict(store: dict, key: tuple, value: Any, max_entries: int) -> None:
    if key in store:
        del store[key]
    elif len(store) >= max_entries:
        store.pop(next(iter(store)), None)
    store[key] = value


def swr_get(store: dict, key: tuple, epoch: Any) -> tuple[bool, Any]:
    """(fresh, bundle): fresh=True when the cached bundle matches the
    current epoch. Otherwise the stale bundle (serve it now and rebuild
    in the background) or None (nothing cached; the caller builds
    inline)."""
    hit = store.get(key)
    if hit is None:
        return False, None
    # Refresh insertion order on hit so LRU eviction keeps hot pages.
    del store[key]
    store[key] = hit
    old_epoch, bundle = hit
    return old_epoch == epoch, bundle


def swr_put(
    store: dict, key: tuple, epoch: Any, bundle: Any, max_entries: int = SWR_MAX_ENTRIES
) -> None:
    _touch_and_evict(store, key, (epoch, bundle), max_entries)


def swr_schedule(store: dict, key: tuple, factory: Any) -> bool:
    """Spawn one background rebuild for key; factory is a zero-arg
    coroutine returning (epoch, bundle). False when a rebuild for this
    key is already in flight."""
    if key in _rebuilding:
        return False
    _rebuilding.add(key)

    async def _run() -> None:
        try:
            epoch, bundle = await factory()
            swr_put(store, key, epoch, bundle)
        except Exception:
            logger.exception("swr rebuild failed for %s", key)
        finally:
            _rebuilding.discard(key)

    task = asyncio.create_task(_run())
    _rebuild_tasks.add(task)
    task.add_done_callback(_rebuild_tasks.discard)
    return True


def cache_get(store: dict, key: tuple, ttl_seconds: float) -> Any | None:
    """store[key] when present and fresh, else None."""
    hit = store.get(key)
    if hit and time.monotonic() - hit[0] < ttl_seconds:
        del store[key]
        store[key] = hit
        return hit[1]
    return None


def cache_put(store: dict, key: tuple, value: Any, max_entries: int = FACET_MAX_ENTRIES) -> None:
    _touch_and_evict(store, key, (time.monotonic(), value), max_entries)


def invalidate_prefix(prefix: str) -> None:
    """Drop cached entries whose tuple key starts with `prefix`."""
    for store in (SWR_CACHE, SNAPSHOT_CACHE, FACET_CACHE):
        for key in [k for k in store if k and k[0] == prefix]:
            store.pop(key, None)
