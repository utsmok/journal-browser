"""Admin panel API: password gate, run listing, flagged deals, settings."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import requires_db
from journal_browser.config import get_settings, reset_settings_cache
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
async def admin_api(db_engine, monkeypatch, tmp_path):
    monkeypatch.setenv("JB_ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setenv("JB_SETTINGS_YAML", str(tmp_path / "settings.yaml"))
    reset_settings_cache()
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    async with maker() as session:
        home = Institution(name="University of Twente", code="ut", active=True)
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
    reset_settings_cache()


async def _login(client: AsyncClient) -> dict[str, str]:
    r = await client.post("/api/v1/admin/login", json={"password": PASSWORD})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


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
    assert settings["values"]["bootstrap"] in {"auto", "always", "off"}
    assert settings["values"]["admin_password"] == "********"
    assert "institution_name" not in settings["values"]
    assert any(
        f["key"] == "institution_name" and f["section"] == "institution"
        for f in settings["schema"]
    )


@requires_db
async def test_settings_put_roundtrip_and_masking(admin_api, tmp_path):
    headers = await _login(admin_api)
    yaml_path = tmp_path / "settings.yaml"
    r = await admin_api.put(
        "/api/v1/admin/settings",
        headers=headers,
        json={
            "values": {
                "bootstrap": "always",
                "ignored_issns": ["1234-5678"],
                "pure_oai_min_spacing": 2.5,
            }
        },
    )
    assert r.status_code == 200
    assert r.json()["values"]["bootstrap"] == "always"
    # Written atomically to the YAML overlay and live for get_settings().
    text = yaml_path.read_text()
    assert "bootstrap: always" in text
    assert "1234-5678" in text
    assert get_settings().bootstrap == "always"
    assert get_settings().ignored_issns == ["1234-5678"]
    # Masked secret keeps the existing value and never lands in the file.
    r = await admin_api.put(
        "/api/v1/admin/settings", headers=headers, json={"values": {"admin_password": "********"}}
    )
    assert r.status_code == 200
    assert "admin_password" not in yaml_path.read_text()
    assert get_settings().admin_password == PASSWORD
    # Validation: unknown key, wrong type, institution-section key.
    for bad in ({"nope": 1}, {"bootstrap": True}, {"institution_name": "X"}):
        r = await admin_api.put("/api/v1/admin/settings", headers=headers, json={"values": bad})
        assert r.status_code == 400
    # A newly written secret takes effect immediately (the token MAC derives
    # from the live settings).
    r = await admin_api.put(
        "/api/v1/admin/settings", headers=headers, json={"values": {"admin_password": "pw2"}}
    )
    assert r.status_code == 200
    r = await admin_api.post("/api/v1/admin/login", json={"password": "pw2"})
    assert r.status_code == 200


@requires_db
async def test_institutions_get_put(admin_api):
    headers = await _login(admin_api)
    r = await admin_api.get("/api/v1/admin/institutions/ut", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == "ut"
    assert body["name"] == "University of Twente"
    r = await admin_api.get("/api/v1/admin/institutions/zz", headers=headers)
    assert r.status_code == 404
    # Unknown/immutable key rejected before anything is applied.
    r = await admin_api.put(
        "/api/v1/admin/institutions/ut",
        headers=headers,
        json={"data_window_start": 2019, "code": "rug"},
    )
    assert r.status_code == 422
    r = await admin_api.get("/api/v1/admin/institutions/ut", headers=headers)
    assert r.json()["data_window_start"] == 2020
    r = await admin_api.put(
        "/api/v1/admin/institutions/ut",
        headers=headers,
        json={"data_window_start": 2019, "active": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["data_window_start"] == 2019
    assert body["active"] is True
    # Author-search confirmation flag round-trips (default on).
    assert body["require_confirmed_affiliation"] is True
    r = await admin_api.put(
        "/api/v1/admin/institutions/ut",
        headers=headers,
        json={"require_confirmed_affiliation": False},
    )
    assert r.status_code == 200
    assert r.json()["require_confirmed_affiliation"] is False
    for bad in (
        {"data_window_start": "x"},
        {"active": "yes"},
        {"require_confirmed_affiliation": 1},
    ):
        r = await admin_api.put("/api/v1/admin/institutions/ut", headers=headers, json=bad)
        assert r.status_code == 422


def test_get_settings_live_yaml_merge(tmp_path, monkeypatch):
    yaml_path = tmp_path / "settings.yaml"
    monkeypatch.setenv("JB_SETTINGS_YAML", str(yaml_path))
    reset_settings_cache()
    try:
        fallback = get_settings().bootstrap
        # Bare `off` would parse as boolean False (YAML 1.1) and fail
        # validation loudly — hand edits must quote such scalars.
        yaml_path.write_text("bootstrap: 'off'\nignored_issns: ['1111-2222']\n")
        assert get_settings().bootstrap == "off"
        assert get_settings().ignored_issns == ["1111-2222"]
        assert get_settings().database_url  # env fallback untouched
        yaml_path.unlink()
        assert get_settings().bootstrap == fallback
    finally:
        reset_settings_cache()


@requires_db
async def test_feedback_limit_rejects_nonpositive(admin_api):
    headers = await _login(admin_api)
    res = await admin_api.get("/api/v1/admin/feedback", params={"limit": -1}, headers=headers)
    assert res.status_code == 422


@requires_db
async def test_institution_put_rejects_null_nonnullable(admin_api):
    headers = await _login(admin_api)
    for key in ("name", "data_window_start", "data_window_end", "active"):
        r = await admin_api.put(
            "/api/v1/admin/institutions/ut", headers=headers, json={key: None}
        )
        assert r.status_code == 422, key
    # A nullable field still clears on explicit null.
    r = await admin_api.put(
        "/api/v1/admin/institutions/ut", headers=headers, json={"admin_contact": None}
    )
    assert r.status_code == 200
    assert r.json()["admin_contact"] is None
