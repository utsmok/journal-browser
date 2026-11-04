"""Admin usage summary: aggregate rollups and auth gating."""

import pytest

from conftest import requires_db
from journal_browser.config import reset_settings_cache
from journal_browser.models import UsageEvent

PASSWORD = "test-admin-pw"


@pytest.fixture
async def usage_api(client, monkeypatch, tmp_path):
    monkeypatch.setenv("JB_ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setenv("JB_SETTINGS_YAML", str(tmp_path / "settings.yaml"))
    reset_settings_cache()
    yield client
    reset_settings_cache()


async def _login(client) -> dict[str, str]:
    r = await client.post("/api/v1/admin/login", json={"password": PASSWORD})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def _seed(db, session_id: str, event_type: str, **kw):
    db.add(
        UsageEvent(
            session_id=session_id,
            event_type=event_type,
            path=kw.pop("path", "/ut"),
            **kw,
        )
    )
    await db.commit()


@requires_db
async def test_summary_requires_admin(usage_api):
    r = await usage_api.get("/api/v1/admin/usage/summary")
    assert r.status_code == 401


@requires_db
async def test_summary_aggregates(usage_api, db):
    await _seed(db, "s1", "page_view", path="/ut/journals/0378-5955", duration_ms=1000)
    await _seed(db, "s1", "page_view", path="/ut/journals/0378-5955", duration_ms=3000)
    await _seed(db, "s2", "page_view", path="/ut")
    await _seed(db, "s1", "search", query="biochemistry", results_count=42, search_scope="journals")
    await _seed(db, "s2", "search", query="biochemistry", results_count=0)
    await _seed(
        db,
        "s3",
        "error",
        source="api_status",
        status=500,
        message="boom",
        detail="GET /x 500",
    )
    await _seed(db, "s3", "page_view", path="/ut", country="NL", ref_type="journal", ref_id="x")
    await db.commit()

    headers = await _login(usage_api)
    r = await usage_api.get("/api/v1/admin/usage/summary?days=30", headers=headers)
    assert r.status_code == 200
    body = r.json()

    assert body["days"] == 30
    assert body["totals"] == {"page_view": 4, "search": 2, "error": 1}
    assert body["sessions"] == 3

    day = body["daily"][-1]
    assert day["page_view"] == 4 and day["search"] == 2 and day["error"] == 1

    paths = {p["path"]: p for p in body["top_paths"]}
    assert paths["/ut/journals/0378-5955"]["page_views"] == 2
    assert paths["/ut/journals/0378-5955"]["avg_duration_ms"] == 2000.0
    assert paths["/ut"]["page_views"] == 2

    (top_query,) = body["top_queries"]
    assert top_query["query"] == "biochemistry"
    assert top_query["count"] == 2
    assert top_query["zero_share"] == 0.5

    (top_ref,) = body["top_refs"]
    assert top_ref == {"ref_type": "journal", "ref_id": "x", "count": 1}

    (err,) = body["errors"]
    assert err["source"] == "api_status"
    assert err["status"] == 500
    assert err["message"] == "boom"
    assert err["count"] == 1
    assert err["last_ts"]

    (country,) = body["countries"]
    assert country == {"country": "NL", "count": 1}


@requires_db
async def test_summary_searches_split(usage_api, db):
    await _seed(db, "s1", "search", query="biochemistry", results_count=42)
    await _seed(db, "s2", "search", is_browse=True)
    await _seed(db, "s2", "page_view")
    await db.commit()
    headers = await _login(usage_api)
    r = await usage_api.get("/api/v1/admin/usage/summary?days=30", headers=headers)
    assert r.status_code == 200
    assert r.json()["searches"] == {"browse": 1, "queries": 1}


@requires_db
async def test_summary_clamps_days(usage_api, db):
    await _seed(db, "s1", "page_view")
    headers = await _login(usage_api)
    r = await usage_api.get("/api/v1/admin/usage/summary?days=99999", headers=headers)
    assert r.status_code == 200
    assert r.json()["days"] == 365
    r = await usage_api.get("/api/v1/admin/usage/summary?days=0", headers=headers)
    assert r.json()["days"] == 1
