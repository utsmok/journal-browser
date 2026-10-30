"""Monotonic-TTL caches shared by search facets and the publisher snapshot.
A harvest bump (cache_epoch in the key) invalidates sooner than the TTL."""

import time
from typing import Any

# Stores live here so the TTL/get/put pattern has exactly one home.
FACET_CACHE: dict[tuple, tuple[float, Any]] = {}
SNAPSHOT_CACHE: dict[tuple, tuple[float, Any]] = {}


def cache_get(store: dict, key: tuple, ttl_seconds: float) -> Any | None:
    """store[key] when present and fresh, else None."""
    hit = store.get(key)
    if hit and time.monotonic() - hit[0] < ttl_seconds:
        return hit[1]
    return None


def cache_put(store: dict, key: tuple, value: Any) -> None:
    store[key] = (time.monotonic(), value)
