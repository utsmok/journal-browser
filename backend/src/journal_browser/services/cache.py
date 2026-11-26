"""Monotonic-TTL caches shared by search facets and the publisher/unit
snapshots. A harvest bump (cache_epoch in the key) invalidates sooner
than the TTL.

Every store is a dict in least-recently-used order, one entry per key:
(stamp or epoch, value, size, seq). size estimates the RAM the value
holds and seq orders reads and writes, so the one budget the three
stores share (JB_CACHE_MAX_MB) drops the least recently used entry
wherever it sits."""

import asyncio
import itertools
import logging
import sys
import time
from typing import Any

from ..config import get_settings

#: Snapshot lifetime in seconds; a harvest bump invalidates sooner.
SNAPSHOT_TTL = 86400

#: Bounded LRU-style caps so long-running processes stay flat in RAM.
SWR_MAX_ENTRIES = 512
FACET_MAX_ENTRIES = 512
SNAPSHOT_MAX_ENTRIES = 256

# Stores live here so the TTL/get/put pattern has exactly one home.
FACET_CACHE: dict[tuple, tuple] = {}
SNAPSHOT_CACHE: dict[tuple, tuple] = {}

logger = logging.getLogger(__name__)

# Stale-while-revalidate detail bundles. A harvest bump changes cache_epoch,
# which invalidates every epoch-keyed cache at once; without SWR each detail
# page pays its full cold build right after every harvest wave (60+ s under
# load). SWR serves the previous epoch's bundle immediately and rebuilds in
# the background, so visitors never wait on a rebuild they did not cause.
SWR_CACHE: dict[tuple, tuple] = {}
_rebuilding: set[tuple] = set()
_rebuild_tasks: set[asyncio.Task] = set()


#: Containers with more items than this are sized from an even sample.
_SAMPLE = 128

#: Recency stamp over reads and writes in every store.
_seq = itertools.count()


def _nbytes(value: Any) -> int:
    """RAM estimate of a cached value: sys.getsizeof summed over the object
    tree, shared objects counted once. A container with more than _SAMPLE
    items is sized from a sample, which keeps the largest snapshot (12,000
    org units) at a few milliseconds."""
    return _walk(value, set())


def _walk(value: Any, seen: set[int]) -> int:
    if id(value) in seen:
        return 0
    seen.add(id(value))
    total = sys.getsizeof(value)
    if isinstance(value, dict):
        count, items = len(value), value.items()
    elif isinstance(value, (list, tuple, set, frozenset)):
        count, items = len(value), ((None, item) for item in value)
    else:
        # Plain objects: the instance dict and the slot members (pydantic
        # keeps the set of assigned fields in a slot, not in __dict__).
        state = getattr(value, "__dict__", None)
        if state is not None:
            total += _walk(state, seen)
        slots = getattr(type(value), "__slots__", ())
        return total + sum(_walk(getattr(value, s), seen) for s in slots if hasattr(value, s))
    if not count:
        return total
    sample = list(itertools.islice(items, 0, None, max(1, count // _SAMPLE)))
    return total + sum(_walk(k, seen) + _walk(v, seen) for k, v in sample) * count // len(sample)


def _shared_stores(store: dict) -> list[dict]:
    """The stores on one byte budget with `store`: the three module stores,
    or only `store` itself when it is not one of them (tests)."""
    stores = [FACET_CACHE, SNAPSHOT_CACHE, SWR_CACHE]
    return stores if any(s is store for s in stores) else [store]


def _touch_and_evict(store: dict, key: tuple, entry: tuple, max_entries: int) -> None:
    """Insert or refresh `key` as the most recent entry, then drop least
    recently used entries until the store fits its entry cap and the
    shared stores fit JB_CACHE_MAX_MB. The entry just written always
    stays, even when it alone exceeds the byte cap."""
    store.pop(key, None)
    store[key] = (*entry, _nbytes(entry[1]), next(_seq))
    if len(store) > max_entries:
        store.pop(next(iter(store)))
    stores = _shared_stores(store)
    max_bytes = get_settings().cache_max_mb * 1024 * 1024
    used = sum(e[2] for s in stores for e in s.values())
    while sum(map(len, stores)) > 1 and used > max_bytes:
        # Every store is in its own recency order, so the oldest of their
        # first entries is the least recently used entry overall.
        oldest = min((s for s in stores if s), key=lambda s: s[next(iter(s))][3])
        used -= oldest.pop(next(iter(oldest)))[2]


def swr_get(store: dict, key: tuple, epoch: Any) -> tuple[bool, Any]:
    """(fresh, bundle): fresh=True when the cached bundle matches the
    current epoch. Otherwise the stale bundle (serve it now and rebuild
    in the background) or None (nothing cached; the caller builds
    inline)."""
    hit = store.get(key)
    if hit is None:
        return False, None
    # Refresh as most recent so eviction keeps hot pages.
    del store[key]
    store[key] = (*hit[:3], next(_seq))
    old_epoch, bundle = hit[:2]
    return old_epoch == epoch, bundle


def swr_put(
    store: dict, key: tuple, epoch: Any, bundle: Any, max_entries: int = SWR_MAX_ENTRIES
) -> None:
    if bundle is None:
        # A rebuild found the entity gone (a harvest deleted it). None is
        # never a bundle to serve, and the stale one must not outlive it:
        # the next request builds inline and answers 404.
        store.pop(key, None)
        return
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
    if hit is None:
        return None
    if time.monotonic() - hit[0] < ttl_seconds:
        del store[key]
        store[key] = (*hit[:3], next(_seq))
        return hit[1]
    store.pop(key, None)
    return None


def cache_put(store: dict, key: tuple, value: Any, max_entries: int | None = None) -> None:
    limit = (
        max_entries
        if max_entries is not None
        else (SNAPSHOT_MAX_ENTRIES if store is SNAPSHOT_CACHE else FACET_MAX_ENTRIES)
    )
    _touch_and_evict(store, key, (time.monotonic(), value), limit)


def invalidate_prefix(prefix: str) -> None:
    """Drop cached entries whose tuple key starts with `prefix`."""
    for store in (SWR_CACHE, SNAPSHOT_CACHE, FACET_CACHE):
        for key in [k for k in store if k and k[0] == prefix]:
            store.pop(key, None)
