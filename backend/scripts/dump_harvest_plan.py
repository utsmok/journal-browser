"""Dump the bootstrap harvest plan to JSON for the data-pipeline page.

The page's step list, dependency edges, and runbook render from this file,
so they cannot drift from the plan that actually runs. Regenerate after
any change to jobs/bootstrap.py:

    cd backend && uv run python scripts/dump_harvest_plan.py \
        --out ../frontend/lib/data-pipeline-plan.json
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from jobs.bootstrap import GLOBAL_DEPS, INST_STEPS, build_plan  # noqa: E402

PLACEHOLDER_CODE = "code"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default="../frontend/lib/data-pipeline-plan.json",
        help="output path (default: ../frontend/lib/data-pipeline-plan.json)",
    )
    args = parser.parse_args()

    global_names = set(GLOBAL_DEPS)
    inst_names = {name for name, _ in INST_STEPS}

    def unqualify(dep: str) -> str:
        return dep.removesuffix(f":{PLACEHOLDER_CODE}")

    steps, deps = build_plan([PLACEHOLDER_CODE], only_institution=None)
    plan_steps = []
    for name, job_args in steps:
        bare = unqualify(name)
        if bare in global_names:
            band = "global"
        elif bare in inst_names:
            band = "institution"
        else:
            band = "final"
        plan_steps.append(
            {
                "id": bare,
                "band": band,
                "script": Path(job_args[0]).name,
                "deps": sorted(unqualify(dep) for dep in deps[name]),
            }
        )

    payload = {"generatedAt": date.today().isoformat(), "steps": plan_steps}
    out = Path(args.out)
    out.write_text(json.dumps(payload, indent=2) + "\n")
    edges = sum(len(s["deps"]) for s in plan_steps)
    print(f"wrote {out}: {len(plan_steps)} steps, {edges} dependency edges")


if __name__ == "__main__":
    main()
