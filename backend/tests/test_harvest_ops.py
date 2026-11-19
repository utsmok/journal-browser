"""Harvest machinery outcomes: paced singletons, source health, issn_map
pruning, journal-flag refresh, journal-citations gating, and bootstrap
auto-mode progress. Replaces test_paced_gets.py, test_source_health.py,
test_issn_map_prune.py, test_flags_prune.py, test_scaffolds.py and
test_bootstrap_auto.py."""

import importlib.util
import sys
import types
from pathlib import Path

import httpx
import pytest
from bibliofabric.exceptions import APIError, NotFoundError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import journal_factory, requires_db
from journal_browser.config import reset_settings_cache
from journal_browser.harvest.common import paced_single_gets
from journal_browser.harvest.denorm import refresh_deal_flags, refresh_institution_stats
from journal_browser.harvest.journal_citations import cited_by_institution
from journal_browser.harvest.openalex_journals import prune_orphan_issn_map
from journal_browser.models import HarvestState, Institution, IssnMap, Journal
from journal_browser.services import source_health
from journal_browser.services.search import _year_rate


def _api_error(status: int) -> APIError:
    cls = NotFoundError if status == 404 else APIError
    return cls(
        f"status {status}",
        response=httpx.Response(status_code=status, request=httpx.Request("GET", "https://x.test")),
    )


async def test_paced_gets_isolation_and_all_failed():
    async def get(iid: str):
        if iid == "gone":
            raise _api_error(404)  # 404 is an isolated miss, not a failure
        if iid == "bad":
            raise _api_error(500)
        return {"id": iid}

    out, failed = await paced_single_gets(get, ["gone", "bad", "here"])
    assert out == {"gone": None, "bad": None, "here": {"id": "here"}}
    assert set(failed) == {"bad"} and isinstance(failed["bad"], APIError)

    async def all_bad(iid: str):
        raise _api_error(500)

    with pytest.raises(RuntimeError, match="all 2 lookups failed"):
        await paced_single_gets(all_bad, ["a", "b"])


# ── Degraded-source registry ──────────────────────────────────────────────


def test_source_health_registry_and_freshness_endpoint(client):
    source_health.clear_all()
    source_health.record_degraded("src-a", "first")
    source_health.record_degraded("src-b", "down")
    source_health.record_degraded("src-a", "second")  # same source: detail replaced
    entries = source_health.snapshot()
    assert [(e["source"], e["detail"]) for e in entries] == [
        ("src-a", "second"),
        ("src-b", "down"),
    ]
    assert isinstance(entries[0]["since"], float)
    source_health.clear("src-a")
    assert [e["source"] for e in source_health.snapshot()] == ["src-b"]
    source_health.clear_all()


@requires_db
async def test_freshness_endpoint_carries_degraded_entry(client, db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        session.add(Institution(name="University of Twente", code="ut", active=True))
        await session.commit()
    source_health.clear_all()
    source_health.record_degraded("ut-metadata", "works query failed; serving stats-only")
    try:
        r = await client.get("/api/v1/ut/meta/freshness")
        assert r.status_code == 200
        degraded = r.json()["degraded"]
        assert [(d["source"], d["detail"]) for d in degraded] == [
            ("ut-metadata", "works query failed; serving stats-only")
        ]
        assert degraded[0]["since"].endswith("Z")
    finally:
        source_health.clear("ut-metadata")
    r = await client.get("/api/v1/ut/meta/freshness")
    assert r.json()["degraded"] == []


async def test_currency_failure_records_degradation():
    source_health.clear("currency-rates")
    assert _year_rate("NOT_A_CURRENCY") is None
    entries = source_health.snapshot()
    assert entries[0]["source"] == "currency-rates" and "NOT_A_CURRENCY" in entries[0]["detail"]
    source_health.clear("currency-rates")


# ── issn_map pruning ──────────────────────────────────────────────────────


@requires_db
async def test_prune_orphan_issn_map_is_idempotent(db):
    db.add(journal_factory("1234-5678"))
    db.add_all(
        [
            IssnMap(issn="1111-1111", issn_l="1234-5678", source="openalex"),  # target exists
            IssnMap(issn="2222-2222", issn_l="9999-9999", source="openalex"),  # orphan
        ]
    )
    await db.commit()
    assert await prune_orphan_issn_map(db) == 1
    await db.commit()
    remaining = {m.issn for m in (await db.execute(select(IssnMap))).scalars()}
    assert remaining == {"1111-1111"}
    assert await prune_orphan_issn_map(db) == 0  # rerun prunes nothing


# ── Journal flags refresh ─────────────────────────────────────────────────


@requires_db
async def test_denorm_refresh_yields_one_row_per_journal(db, institution_factory):
    active = await institution_factory(code="ut")
    await institution_factory()  # no code: inactive, never materialized
    for issn in ("0000-0001", "0000-0002", "0000-0003"):
        db.add(Journal(issn_l=issn, title=f"J {issn}"))
    await db.commit()
    await refresh_institution_stats(db, active)
    await refresh_deal_flags(db, active.id)
    counts = (
        await db.execute(text("SELECT institution_id, count(*) FROM journal_flags GROUP BY 1"))
    ).all()
    assert counts == [(active.id, 3)]


# ── Journal-citations gate ────────────────────────────────────────────────


async def test_journal_citations_refuses_when_disabled(monkeypatch):
    monkeypatch.setenv("JB_ENABLE_JOURNAL_CITATIONS", "false")
    reset_settings_cache()
    try:
        with pytest.raises(RuntimeError, match="disabled"):
            await cited_by_institution(None, "S123", "I94624287")
    finally:
        reset_settings_cache()


# ── Bootstrap auto-mode progress ──────────────────────────────────────────


_spec = importlib.util.spec_from_file_location(
    "bootstrap_ops_mod", Path(__file__).resolve().parents[1] / "jobs" / "bootstrap.py"
)
bootstrap_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bootstrap_mod)


@requires_db
async def test_bootstrap_progress_states(db):
    assert await bootstrap_mod._bootstrap_progress(db) == (False, False)  # fresh database
    db.add(journal_factory("1234-5678"))
    await db.commit()
    assert await bootstrap_mod._bootstrap_progress(db) == (True, False)  # journals only
    db.add(
        HarvestState(
            source="local", entity_type="bootstrap_plan", filter_set="backfill", status="completed"
        )
    )
    await db.commit()
    assert await bootstrap_mod._bootstrap_progress(db) == (True, True)  # plan marker written


def _patch_auto_mode(monkeypatch, progress):
    async def fake_progress():
        return progress

    async def fake_codes():
        return ["ut"]

    monkeypatch.setattr(bootstrap_mod, "bootstrap_progress", fake_progress)
    monkeypatch.setattr(bootstrap_mod, "hosted_codes", fake_codes)
    monkeypatch.setattr(
        bootstrap_mod, "get_settings", lambda: types.SimpleNamespace(bootstrap="auto")
    )
    monkeypatch.setattr(sys, "argv", ["bootstrap.py"])


async def test_auto_mode_refuses_partial(monkeypatch, capsys):
    _patch_auto_mode(monkeypatch, (True, False))
    assert await bootstrap_mod.main() == 1
    assert "partial bootstrap" in capsys.readouterr().err


async def test_auto_mode_skips_complete(monkeypatch, capsys):
    _patch_auto_mode(monkeypatch, (True, True))
    assert await bootstrap_mod.main() == 0
    assert "nothing to do" in capsys.readouterr().out
