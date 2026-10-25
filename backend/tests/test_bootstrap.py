"""The bootstrap DAG must stay acyclic and match the listed step order."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "bootstrap_dag", Path(__file__).resolve().parents[1] / "jobs" / "bootstrap.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

DEPS = _mod.DEPS
STEPS = _mod.STEPS


def test_deps_cover_exactly_the_steps() -> None:
    names = {name for name, _ in STEPS}
    assert set(DEPS) == names


def test_deps_exist_and_follow_topological_order() -> None:
    order = [name for name, _ in STEPS]
    for name, deps in DEPS.items():
        for dep in deps:
            assert dep in DEPS, f"unknown dependency {dep!r} of {name!r}"
            assert order.index(dep) < order.index(name), (
                f"{name!r} must come after its dependency {dep!r}"
            )
