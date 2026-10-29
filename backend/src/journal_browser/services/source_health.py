"""Registry of degraded serving-time sources; surfaced via /meta/freshness.

Per-process by design: the deployment is a single uvicorn worker. If the app
ever scales past one worker, back this with the harvest_runs table or Redis;
the record_degraded/clear/snapshot interface stays.
"""

import threading
import time

_lock = threading.Lock()
_degraded: dict[str, tuple[str, float]] = {}


def record_degraded(source: str, detail: str) -> None:
    """Mark a source degraded; keeps the most recent detail per source."""
    with _lock:
        _degraded[source] = (detail, time.time())


def clear(source: str) -> None:
    with _lock:
        _degraded.pop(source, None)


def snapshot() -> list[dict]:
    with _lock:
        return [
            {"source": s, "detail": d, "since": ts}
            for s, (d, ts) in sorted(_degraded.items())
        ]
