"""Degraded-source registry: round-trip, freshness surfacing, currency swallow."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import requires_db
from journal_browser.models import Institution
from journal_browser.services import source_health
from journal_browser.services.search import _year_rate


def test_registry_round_trip():
    source_health.record_degraded("src-a", "first")
    source_health.record_degraded("src-b", "down")
    source_health.record_degraded("src-a", "second")
    entries = source_health.snapshot()
    assert [(e["source"], e["detail"]) for e in entries] == [
        ("src-a", "second"),
        ("src-b", "down"),
    ]
    assert isinstance(entries[0]["since"], float)
    source_health.clear("src-a")
    assert [e["source"] for e in source_health.snapshot()] == ["src-b"]
    source_health.clear("src-b")
    assert source_health.snapshot() == []


@requires_db
@pytest.fixture
async def health_api(client, db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async with maker() as session:
        session.add(Institution(name="University of Twente", code="ut", active=True))
        await session.commit()
    return client


@requires_db
async def test_freshness_carries_degraded_entry(health_api):
    source_health.record_degraded("ut-metadata", "works query failed; serving stats-only")
    try:
        r = await health_api.get("/api/v1/ut/meta/freshness")
        assert r.status_code == 200
        degraded = r.json()["degraded"]
        assert len(degraded) == 1
        assert degraded[0]["source"] == "ut-metadata"
        assert degraded[0]["detail"] == "works query failed; serving stats-only"
        assert degraded[0]["since"].endswith("Z")
    finally:
        source_health.clear("ut-metadata")
    r = await health_api.get("/api/v1/ut/meta/freshness")
    assert r.json()["degraded"] == []


async def test_currency_failure_records_degradation():
    source_health.clear("currency-rates")
    assert _year_rate("NOT_A_CURRENCY") is None
    entries = source_health.snapshot()
    assert entries[0]["source"] == "currency-rates"
    assert "NOT_A_CURRENCY" in entries[0]["detail"]
    source_health.clear("currency-rates")
