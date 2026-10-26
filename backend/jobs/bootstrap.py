"""Initial-deployment pipeline: every job as a dependency DAG, one command.

Designed for a fresh database. docker compose boots this once via the
`bootstrap` service; in auto mode (default) it skips when journals already
exist, so restarts are cheap. Independent steps run concurrently (the
journals sweep dominates wall time while Pure/OpenAPC/deal scrapes run
beside it). Every step is an idempotent standalone job; a failure stops
new steps from starting and names the failed ones.

Two layers: global steps build the shared core once (journals universe,
deal register, OpenAPC, Scimago, ISSN-L); per-institution steps run once
for every hosted institution (Pure, enrich, OpenAIRE, stats). Embeddings
are institution-neutral and run last. `--institution CODE` runs only that
institution's layer (onboarding = one institutions row + this).

Usage: uv run python jobs/bootstrap.py [--always] [--from STEP]
       uv run python jobs/bootstrap.py --institution rug
"""

import asyncio
import sys
import time
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.common import get_active_institutions
from journal_browser.models import Journal

BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Topological order (also the --from resume order). DEPS gates concurrency.
GLOBAL_STEPS: list[tuple[str, list[str]]] = [
    ("journals", ["jobs/harvest_journals.py"]),
    ("deals-openaccess-nl", ["jobs/scrape_openaccess_nl.py"]),
    ("deals-jct", ["jobs/ingest_jct.py"]),
    ("openapc", ["jobs/ingest_openapc.py"]),
    # pattern derivation needs publisher names; matching needs both sources
    ("deals-reconcile", ["jobs/reconcile.py"]),
    ("deals-issn-l", ["jobs/backfill_issn_l.py"]),
    ("scimagojr", ["jobs/ingest_scimagojr.py"]),
    ("flags", ["jobs/backfill_flags.py"]),
]

GLOBAL_DEPS: dict[str, list[str]] = {
    "journals": [],
    "deals-openaccess-nl": [],
    "deals-jct": [],
    "openapc": [],  # aggregates are ISSN-keyed, no journals needed
    "deals-reconcile": ["journals", "deals-openaccess-nl", "deals-jct"],
    "deals-issn-l": ["deals-reconcile"],
    "scimagojr": ["journals"],  # resolves ISSNs against the journals universe
    "flags": ["journals"],  # works_2020_plus / last_active_year recompute
}

#: Per-institution layer, in order. Every step takes --institution CODE.
INST_STEPS: list[tuple[str, list[str]]] = [
    ("pure", ["jobs/harvest_pure.py", "--full-sweep"]),
    ("enrich", ["jobs/enrich_works.py"]),
    ("openaire", ["jobs/harvest_openaire.py"]),
    ("stats", ["jobs/harvest_stats.py"]),
    # Participation derive + coverage flags: makes onboarding (one row +
    # this layer) self-sufficient without rerunning global deal merging.
    ("reconcile", ["jobs/reconcile.py"]),
]

#: Per-institution dependencies: names within an institution are prefixed
#: "step:code"; cross-layer deps name global steps.
INST_DEPS: dict[str, list[str]] = {
    "pure": [],
    "enrich": ["pure"],
    # DOI-to-work matching reads the institution's works
    "openaire": ["pure", "deals-issn-l"],
    "stats": ["enrich", "openaire", "openapc", "scimagojr", "flags"],
    "reconcile": ["stats", "deals-reconcile"],
}

#: Institution-neutral, so it runs once after every stats layer.
EMBEDDINGS_STEP = ("embeddings", ["jobs/embed_journals.py"])


async def hosted_codes() -> list[str]:
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        codes = [inst.code for inst in await get_active_institutions(session)]
    await engine.dispose()
    return [c for c in codes if c]


async def already_bootstrapped() -> bool:
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        count = await session.scalar(select(func.count()).select_from(Journal))
    await engine.dispose()
    return bool(count)


def _step_after(args: list[str]) -> str | None:
    """Parse --from STEP; resume runs this step and everything after it."""
    if "--from" not in args:
        return None
    i = args.index("--from")
    if i + 1 >= len(args):
        print("bootstrap: --from requires a step name", file=sys.stderr)
        raise SystemExit(2)
    return args[i + 1]


async def run_step(name: str, job_args: list[str]) -> bool:
    started = time.monotonic()
    print(f"bootstrap[{name}]: {' '.join(job_args)}", flush=True)
    proc = await asyncio.create_subprocess_exec(sys.executable, *job_args, cwd=BACKEND_ROOT)
    code = await proc.wait()
    elapsed = time.monotonic() - started
    if code != 0:
        print(f"bootstrap[{name}]: FAILED (exit {code})", flush=True)
        return False
    print(f"bootstrap[{name}]: done in {elapsed:.0f}s", flush=True)
    return True


def build_plan(codes: list[str], only_institution: str | None) -> tuple[list, dict]:
    """(steps, deps) for the run: global layer, per-institution layers,
    embeddings last. only_institution drops the global layer and embeddings
    (they are shared and already built)."""
    steps = list(GLOBAL_STEPS)
    deps = dict(GLOBAL_DEPS)
    stats_names: list[str] = []
    for code in codes:
        for name, job_args in INST_STEPS:
            full = f"{name}:{code}"
            steps.append((full, job_args + ["--institution", code]))
            deps[full] = [
                dep if dep in GLOBAL_DEPS else f"{dep}:{code}" for dep in INST_DEPS[name]
            ]
            if name == "stats":
                stats_names.append(full)
    if only_institution is None:
        steps.append(EMBEDDINGS_STEP)
        deps[EMBEDDINGS_STEP[0]] = stats_names
    else:
        wanted = {f"{name}:{only_institution}" for name, _ in INST_STEPS}
        steps = [s for s in steps if s[0] in wanted]
        deps = {k: v for k, v in deps.items() if k in wanted}
    return steps, deps


async def run_serial(steps: list, deps: dict, from_step: str | None) -> int:
    started = time.monotonic()
    for name, job_args in steps:
        if from_step is not None and name != from_step:
            continue
        from_step = None
        if not await run_step(name, job_args):
            return 1
    print(f"bootstrap: complete in {(time.monotonic() - started) / 60:.0f}m", flush=True)
    return 0


async def run_parallel(steps: list, deps: dict) -> int:
    started = time.monotonic()
    running: dict[asyncio.Task, str] = {}
    done: set[str] = set()
    failed: list[str] = []
    pending = [name for name, _ in steps]
    while pending or running:
        # launch every step whose dependencies succeeded
        for name in list(pending):
            if failed or not all(dep in done for dep in deps[name]):
                continue
            pending.remove(name)
            task = asyncio.create_task(run_step(name, dict(steps)[name]))
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
    only_institution = None
    if "--institution" in args:
        i = args.index("--institution")
        if i + 1 >= len(args):
            print("bootstrap: --institution requires a code", file=sys.stderr)
            return 2
        only_institution = args[i + 1]
    if mode == "off" and only_institution is None:
        print("bootstrap: off (JB_BOOTSTRAP=off)")
        return 0
    codes = await hosted_codes()
    if only_institution is not None and only_institution not in codes:
        print(f"bootstrap: unknown or inactive institution {only_institution!r} "
              f"(hosted: {', '.join(codes) or 'none'})", file=sys.stderr)
        return 2
    if (
        "--from" not in args
        and "--institution" not in args
        and mode == "auto"
        and await already_bootstrapped()
    ):
        print("bootstrap: journals present, nothing to do (use --always to force)")
        return 0
    steps, deps = build_plan(codes, only_institution)
    # --from is repair mode: serial, in listed order
    if resume_from is not None:
        return await run_serial(steps, deps, resume_from)
    return await run_parallel(steps, deps)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
