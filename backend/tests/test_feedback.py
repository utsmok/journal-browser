"""Feedback system: public intake, admin triage, page-data dump storage."""

import pytest
from httpx import AsyncClient

from conftest import requires_db
from journal_browser.config import reset_settings_cache

PASSWORD = "test-admin-pw"


@pytest.fixture
async def feedback_api(client, monkeypatch, tmp_path):
    monkeypatch.setenv("JB_ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setenv("JB_SETTINGS_YAML", str(tmp_path / "settings.yaml"))
    reset_settings_cache()
    return client
    reset_settings_cache()


async def _login(client: AsyncClient) -> dict[str, str]:
    r = await client.post("/api/v1/admin/login", json={"password": PASSWORD})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


DUMP = {
    "url": "/ut/journals?q=water",
    "queries": [{"key": ["journals", "ut", {"q": "water"}], "data": {"items": []}}],
}


@requires_db
async def test_public_create_stores_page_data(feedback_api):
    r = await feedback_api.post(
        "/api/v1/feedback",
        json={
            "title": "Wrong APC price",
            "description": "The list price for ISSN 1234-5678 looks wrong.",
            "category": "bug",
            "page_url": "/ut/journals/1234-5678",
            "page_data": DUMP,
        },
    )
    assert r.status_code == 201
    assert r.json()["status"] == "todo"

    headers = await _login(feedback_api)
    r = await feedback_api.get("/api/v1/admin/feedback", headers=headers)
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["page_data"] == DUMP
    assert items[0]["page_url"] == "/ut/journals/1234-5678"


@requires_db
async def test_create_rejects_bad_category_and_huge_dump(feedback_api):
    r = await feedback_api.post(
        "/api/v1/feedback",
        json={"title": "x", "description": "y", "category": "not-a-thing"},
    )
    assert r.status_code == 422
    r = await feedback_api.post(
        "/api/v1/feedback",
        json={"title": "x", "description": "y", "page_data": {"blob": "a" * 1_100_000}},
    )
    assert r.status_code == 413


@requires_db
async def test_admin_triage_requires_token(feedback_api):
    r = await feedback_api.get("/api/v1/admin/feedback")
    assert r.status_code == 401


@requires_db
async def test_admin_patch_and_status_filter(feedback_api):
    headers = await _login(feedback_api)
    for title in ("a", "b"):
        await feedback_api.post(
            "/api/v1/feedback", json={"title": title, "description": "d"}
        )

    r = await feedback_api.get("/api/v1/admin/feedback", headers=headers)
    first = r.json()[-1]["id"]

    r = await feedback_api.patch(
        f"/api/v1/admin/feedback/{first}",
        headers=headers,
        json={"status": "in_progress", "priority": "high", "resolution_notes": "looking"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "in_progress"

    r = await feedback_api.get(
        "/api/v1/admin/feedback", headers=headers, params={"status": "in_progress"}
    )
    assert [i["id"] for i in r.json()] == [first]

    r = await feedback_api.patch(
        f"/api/v1/admin/feedback/{first}", headers=headers, json={"status": "nope"}
    )
    assert r.status_code == 422


@requires_db
async def test_admin_delete(feedback_api):
    headers = await _login(feedback_api)
    r = await feedback_api.post("/api/v1/feedback", json={"title": "t", "description": "d"})
    fid = r.json()["id"]
    r = await feedback_api.delete(f"/api/v1/admin/feedback/{fid}", headers=headers)
    assert r.status_code == 204
    r = await feedback_api.get("/api/v1/admin/feedback", headers=headers)
    assert r.json() == []
