"""Initial-deployment pipeline: every job in dependency order, one command.

Designed for a fresh database. docker compose boots this once via the
`bootstrap` service; in auto mode (default) it skips when journals already
exist, so restarts are cheap. Every step is an idempotent standalone job; a
failure stops the run and names the step.

Usage: uv run python jobs/bootstrap.py [--always] [--from STEP]
"""

import asyncio
import subprocess
import sys
import time
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from journal_browser.config import get_settings
from journal_browser.models import Journal

BACKEND_ROOT = Path(__file__).resolve().parent.parent

STEPS: list[tuple[str, list[str]]] = [
    ("journals", ["jobs/harvest_journals.py"]),
    ("deals-openaccess-nl", ["jobs/scrape_openaccess_nl.py"]),
    ("deals-jct", ["jobs/ingest_jct.py"]),
    ("deals-reconcile", ["jobs/reconcile.py"]),
    ("deals-purge-foreign", ["jobs/purge_non_twente_deals.py"]),
    ("deals-issn-l", ["jobs/backfill_issn_l.py"]),
    ("openapc", ["jobs/ingest_openapc.py"]),
    ("scimagojr", ["jobs/ingest_scimagojr.py"]),
    ("pure", ["jobs/harvest_pure.py", "--full-sweep"]),
    ("enrich", ["jobs/enrich_works.py"]),
    ("openaire", ["jobs/harvest_openaire.py"]),
    ("stats", ["jobs/harvest_stats.py"]),
    ("flags", ["jobs/backfill_flags.py"]),
    ("embeddings", ["jobs/embed_journals.py"]),
]


async def already_bootstrapped() -> bool:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.connect() as conn:
            count = await conn.scalar(select(func.count()).select_from(Journal))
        return bool(count)
    finally:
        await engine.dispose()


def run_step(name: str, args: list[str]) -> float:
    started = time.monotonic()
    print(f"bootstrap[{name}]: {' '.join(args)}", flush=True)
    result = subprocess.run([sys.executable, *args], cwd=BACKEND_ROOT)
    elapsed = time.monotonic() - started
    if result.returncode != 0:
        print(f"bootstrap[{name}]: FAILED (exit {result.returncode})", flush=True)
        sys.exit(result.returncode)
    print(f"bootstrap[{name}]: done in {elapsed:.0f}s", flush=True)
    return elapsed


def _step_after(args: list[str]) -> str:
    """Parse --from STEP; resume runs this step and everything after it."""
    try:
        name = args[args.index("--from") + 1]
    except (IndexError, ValueError):
        name = ""
    if name not in dict(STEPS):
        sys.exit(f"unknown step {name!r}; valid: {', '.join(n for n, _ in STEPS)}")
    return name


async def main() -> None:
    settings = get_settings()
    args = sys.argv[1:]
    mode = "always" if "--always" in args else settings.bootstrap
    resume_from = _step_after(args) if "--from" in args else None
    if mode == "off":
        print("bootstrap: off (JB_BOOTSTRAP=off)")
        return
    if "--from" not in args and mode == "auto" and await already_bootstrapped():
        print("bootstrap: journals present, nothing to do (use --always to force)")
        return
    started = time.monotonic()
    for name, job_args in STEPS:
        if resume_from is not None and name != resume_from:
            continue
        resume_from = None
        run_step(name, job_args)
    print(f"bootstrap: complete in {(time.monotonic() - started) / 60:.0f}m", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
