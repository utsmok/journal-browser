"""Initial-deployment pipeline: every job as a dependency DAG, one command.

Designed for a fresh database. docker compose boots this once via the
`bootstrap` service; in auto mode (default) it skips when journals already
exist, so restarts are cheap. Independent steps run concurrently (the
journals sweep dominates wall time while Pure/OpenAPC/deal scrapes run
beside it). Every step is an idempotent standalone job; a failure stops
new steps from starting and names the failed ones.

Usage: uv run python jobs/bootstrap.py [--always] [--from STEP]
"""

import asyncio
import sys
import time
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from journal_browser.config import get_settings
from journal_browser.models import Journal

BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Topological order (also the --from resume order). DEPS gates concurrency.
STEPS: list[tuple[str, list[str]]] = [
    ("journals", ["jobs/harvest_journals.py"]),
    ("deals-openaccess-nl", ["jobs/scrape_openaccess_nl.py"]),
    ("deals-jct", ["jobs/ingest_jct.py"]),
    ("openapc", ["jobs/ingest_openapc.py"]),
    ("pure", ["jobs/harvest_pure.py", "--full-sweep"]),
    ("deals-reconcile", ["jobs/reconcile.py"]),
    ("deals-purge-foreign", ["jobs/purge_non_twente_deals.py"]),
    ("deals-issn-l", ["jobs/backfill_issn_l.py"]),
    ("scimagojr", ["jobs/ingest_scimagojr.py"]),
    ("enrich", ["jobs/enrich_works.py"]),
    ("openaire", ["jobs/harvest_openaire.py"]),
    ("stats", ["jobs/harvest_stats.py"]),
    ("flags", ["jobs/backfill_flags.py"]),
    ("embeddings", ["jobs/embed_journals.py"]),
]

DEPS: dict[str, list[str]] = {
    "journals": [],
    "deals-openaccess-nl": [],
    "deals-jct": [],
    "openapc": [],  # aggregates are ISSN-keyed, no journals needed
    "pure": [],
    # pattern derivation needs publisher names; matching needs both sources
    "deals-reconcile": ["journals", "deals-openaccess-nl", "deals-jct"],
    "deals-purge-foreign": ["deals-reconcile"],
    "deals-issn-l": ["deals-purge-foreign"],
    "scimagojr": ["journals"],  # resolves ISSNs against the journals universe
    "enrich": ["pure"],
    "openaire": ["pure"],  # DOI-to-work matching reads ut_works
    "stats": ["deals-issn-l", "openapc", "scimagojr", "enrich", "openaire"],
    "flags": ["deals-reconcile", "stats"],
    "embeddings": ["stats"],  # embeds the stats-built landing text
}


async def already_bootstrapped() -> bool:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.connect() as conn:
            count = await conn.scalar(select(func.count()).select_from(Journal))
        return bool(count)
    finally:
        await engine.dispose()


def _step_after(args: list[str]) -> str:
    """Parse --from STEP; resume runs this step and everything after it."""
    try:
        name = args[args.index("--from") + 1]
    except (IndexError, ValueError):
        name = ""
    if name not in dict(STEPS):
        sys.exit(f"unknown step {name!r}; valid: {', '.join(n for n, _ in STEPS)}")
    return name


async def run_step(name: str, job_args: list[str]) -> bool:
    started = time.monotonic()
    print(f"bootstrap[{name}]: {' '.join(job_args)}", flush=True)
    proc = await asyncio.create_subprocess_exec(
        sys.executable, *job_args, cwd=BACKEND_ROOT
    )
    code = await proc.wait()
    elapsed = time.monotonic() - started
    if code != 0:
        print(f"bootstrap[{name}]: FAILED (exit {code})", flush=True)
        return False
    print(f"bootstrap[{name}]: done in {elapsed:.0f}s", flush=True)
    return True


async def run_serial(from_step: str | None) -> int:
    started = time.monotonic()
    for name, job_args in STEPS:
        if from_step is not None and name != from_step:
            continue
        from_step = None
        if not await run_step(name, job_args):
            return 1
    print(f"bootstrap: complete in {(time.monotonic() - started) / 60:.0f}m", flush=True)
    return 0


async def run_parallel() -> int:
    started = time.monotonic()
    running: dict[asyncio.Task, str] = {}
    done: set[str] = set()
    failed: list[str] = []
    pending = [name for name, _ in STEPS]
    while pending or running:
        # launch every step whose dependencies succeeded
        for name in list(pending):
            if failed or not all(dep in done for dep in DEPS[name]):
                continue
            pending.remove(name)
            task = asyncio.create_task(run_step(name, dict(STEPS)[name]))
            running[task] = name
        if not running:  # only unsatisfiable steps left
            break
        done_tasks, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
        for task in done_tasks:
            name = running.pop(task)
            try:
                ok = task.result()
            except Exception:
                ok = False
            if ok:
                done.add(name)
            else:
                failed.append(name)
    if failed:
        print(f"bootstrap: FAILED steps: {', '.join(failed)}", flush=True)
        return 1
    print(f"bootstrap: complete in {(time.monotonic() - started) / 60:.0f}m", flush=True)
    return 0


async def main() -> int:
    settings = get_settings()
    args = sys.argv[1:]
    mode = "always" if "--always" in args else settings.bootstrap
    resume_from = _step_after(args) if "--from" in args else None
    if mode == "off":
        print("bootstrap: off (JB_BOOTSTRAP=off)")
        return 0
    if "--from" not in args and mode == "auto" and await already_bootstrapped():
        print("bootstrap: journals present, nothing to do (use --always to force)")
        return 0
    # --from is repair mode: serial, in listed order
    if resume_from is not None:
        return await run_serial(resume_from)
    return await run_parallel()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
