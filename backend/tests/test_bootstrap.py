"""The bootstrap DAG must stay acyclic and match the listed step order."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "bootstrap_dag", Path(__file__).resolve().parents[1] / "jobs" / "bootstrap.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def _plan(codes: list[str]):
    return _mod.build_plan(codes, only_institution=None)


def test_plan_deps_cover_exactly_the_steps() -> None:
    steps, deps = _plan(["ut"])
    names = {name for name, _ in steps}
    assert set(deps) == names


def test_plan_deps_exist_and_follow_topological_order() -> None:
    for codes in (["ut"], ["ut", "rug"]):
        steps, deps = _plan(codes)
        order = [name for name, _ in steps]
        for name, dependencies in deps.items():
            for dep in dependencies:
                assert dep in deps, f"unknown dependency {dep!r} of {name!r}"
                assert order.index(dep) < order.index(name), (
                    f"{name!r} must come after its dependency {dep!r}"
                )


def test_institution_layer_included_per_institution() -> None:
    steps, _deps = _plan(["ut", "rug"])
    names = [name for name, _ in steps]
    for code in ("ut", "rug"):
        for step in ("pure", "enrich", "openaire", "stats"):
            assert f"{step}:{code}" in names
    # embeddings wait for every stats layer and close the run
    assert names[-1] == "embeddings"
    assert all(names.index(f"stats:{c}") < names.index("embeddings") for c in ("ut", "rug"))


def test_only_institution_plan_drops_shared_layer() -> None:
    _steps, _deps = _mod.build_plan(["ut", "rug"], only_institution="rug")
    names = [name for name, _ in _steps]
    assert names == [f"{s}:rug" for s, _ in _mod.INST_STEPS]
    assert all(":" in n for n in _deps)
