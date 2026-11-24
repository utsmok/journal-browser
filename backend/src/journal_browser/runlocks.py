"""Run liveness: one flock per harvest run, so a reaper can tell a job that
died (container recreate, OOM kill) from one still working.

IngestSession.start_run takes the lock and finish_run releases it; the
kernel drops it when the process dies. The files live under the landing
directory because compose bind-mounts it into the backend, scheduler and
bootstrap containers alike, so a job started by hand in one container is
visible to the reaper in another. A missing or unlocked file means no live
owner; a file that cannot be opened means "do not know".
"""

import fcntl
import logging
import os
from enum import Enum
from pathlib import Path

from .config import get_settings

logger = logging.getLogger(__name__)

LOCK_SUBDIR = "run-locks"


class LockState(Enum):
    HELD = "held"  # a live process owns the run
    FREE = "free"  # nobody owns the run
    UNKNOWN = "unknown"  # cannot tell: leave the row alone


def run_lock_path(run_id: int) -> Path:
    return Path(get_settings().landing_dir) / LOCK_SUBDIR / f"{run_id}.lock"


def discard_run_lock(run_id: int) -> None:
    """Remove the run's lock file; the lock itself dies with its owner."""
    try:
        run_lock_path(run_id).unlink(missing_ok=True)
    except OSError as exc:
        logger.debug("Run %s: lock file not removed (%s)", run_id, exc)


def acquire_run_lock(run_id: int) -> int | None:
    """Take the run's lock; the returned fd holds it until closed.

    Returns None when the lock cannot be taken. Tracking is best effort
    and must never stop a harvest, so that only costs the reaper its
    evidence for this one run.
    """
    try:
        path = run_lock_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as exc:
        logger.warning("Run %s: no liveness lock (%s)", run_id, exc)
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(fd)
        logger.warning("Run %s: no liveness lock (%s)", run_id, exc)
        return None
    return fd


def release_run_lock(fd: int | None, run_id: int | None) -> None:
    """Drop a lock taken by acquire_run_lock; the file goes with it."""
    if fd is None or run_id is None:
        return
    os.close(fd)
    discard_run_lock(run_id)


def run_lock_state(run_id: int) -> LockState:
    """Who holds the run's lock.

    The lock is probed by trying to take it: a live owner makes that fail
    with EWOULDBLOCK. A probe that succeeds is released again when the fd
    closes.
    """
    try:
        fd = os.open(run_lock_path(run_id), os.O_RDWR)
    except FileNotFoundError:
        return LockState.FREE
    except OSError:
        return LockState.UNKNOWN
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return LockState.HELD
        return LockState.FREE
    finally:
        os.close(fd)
