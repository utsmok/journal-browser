"""Auto mode must distinguish a completed bootstrap from a partial one.

A first bootstrap that died after the journals step used to make every
later auto run exit 0 ("nothing to do"), so a restart silently served a
half-filled database. The completion marker is written by the plan runner
itself (jobs/bootstrap.py, harvest_state local/bootstrap_plan).
"""

import importlib.util
import sys
import types
from pathlib import Path

from conftest import journal_factory
from journal_browser.models import HarvestState

_spec = importlib.util.spec_from_file_location(
    "bootstrap_mod", Path(__file__).resolve().parents[1] / "jobs" / "bootstrap.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


async def test_progress_fresh_database(db):
    assert await _mod._bootstrap_progress(db) == (False, False)


async def test_progress_partial_bootstrap(db):
    db.add(journal_factory("1234-5678"))
    await db.commit()
    assert await _mod._bootstrap_progress(db) == (True, False)


async def test_progress_completed_bootstrap(db):
    db.add(journal_factory("1234-5678"))
    db.add(
        HarvestState(
            source="local",
            entity_type="bootstrap_plan",
            filter_set="backfill",
            status="completed",
        )
    )
    await db.commit()
    assert await _mod._bootstrap_progress(db) == (True, True)


def _patch_auto_mode(monkeypatch, progress):
    async def fake_progress():
        return progress

    async def fake_codes():
        return ["ut"]

    monkeypatch.setattr(_mod, "bootstrap_progress", fake_progress)
    monkeypatch.setattr(_mod, "hosted_codes", fake_codes)
    monkeypatch.setattr(_mod, "get_settings", lambda: types.SimpleNamespace(bootstrap="auto"))
    monkeypatch.setattr(sys, "argv", ["bootstrap.py"])


async def test_auto_mode_refuses_partial(monkeypatch, capsys):
    _patch_auto_mode(monkeypatch, (True, False))
    assert await _mod.main() == 1
    assert "partial bootstrap" in capsys.readouterr().err


async def test_auto_mode_skips_complete(monkeypatch, capsys):
    _patch_auto_mode(monkeypatch, (True, True))
    assert await _mod.main() == 0
    assert "nothing to do" in capsys.readouterr().out
