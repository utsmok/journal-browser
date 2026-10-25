"""Admin panel API: password gate, run listing, flagged deals, settings."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import requires_db
from journal_browser.config import get_settings
from journal_browser.db import get_session
from journal_browser.main import app
from journal_browser.models import (
    Deal,
    DealJournal,
    HarvestRun,
    Institution,
    Journal,
    Publisher,
)

PASSWORD = "test-admin-pw"


@pytest.fixture
async def admin_api(db_engine, monkeypatch):
    monkeypatch.setenv("JB_ADMIN_PASSWORD", PASSWORD)
    get_settings.cache_clear()
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    async with maker() as session:
        home = Institution(name="University of Twente", is_home=True)
        session.add(home)
        await session.flush()
        pub = Publisher(name="Emerald Publishing group")
        session.add(pub)
        await session.flush()
        deal = Deal(
            publisher_id=pub.id,
            status="current",
            corresponding_authors_only=False,
            provenance=[],
            needs_curation=True,
            needs_curation_reason="duplicate sheet",
        )
        session.add(deal)
        await session.flush()
        journal = Journal(issn_l="0000-0000", title="J", publisher_name="Emerald")
        session.add(journal)
        await session.flush()
        session.add(DealJournal(deal_id=deal.id, issn="0000-0000", source="jct"))
        session.add(
            HarvestRun(
                source="reconcile",
                entity_type="deal",
                status="completed",
                config_fingerprint="x",
                stats={"matched": 1},
            )
        )
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@requires_db
async def test_gate_rejects_without_password(admin_api):
    r = await admin_api.get("/api/v1/admin/runs")
    assert r.status_code == 401
    r = await admin_api.post("/api/v1/admin/login", json={"password": "wrong"})
    assert r.status_code == 403


@requires_db
async def test_login_and_runs(admin_api):
    r = await admin_api.post("/api/v1/admin/login", json={"password": PASSWORD})
    assert r.status_code == 200
    token = r.json()["token"]
    r = await admin_api.get(
        "/api/v1/admin/runs", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    runs = r.json()
    sources = {run["source"]: run for run in runs}
    assert sources["reconcile"]["stats"]["matched"] == 1


@requires_db
async def test_flagged_and_settings(admin_api):
    token = (
        await admin_api.post("/api/v1/admin/login", json={"password": PASSWORD})
    ).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    flagged = (await admin_api.get("/api/v1/admin/flagged", headers=headers)).json()
    assert len(flagged) == 1
    assert flagged[0]["journals"] == 1
    assert flagged[0]["reason"] == "duplicate sheet"
    settings = (await admin_api.get("/api/v1/admin/settings", headers=headers)).json()
    assert settings["institution_name"] == "University of Twente"
    assert isinstance(settings["has_openalex_key"], bool)
    assert "openalex_api_key" not in settings
