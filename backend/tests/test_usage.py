"""Usage tracking outcomes: batch intake validation, header enrichment and
search/browse normalization, the tracking flag gate, IP retention pruning,
and the admin analytics summary/events surfaces.

Replaces the old test_usage and test_usage_admin."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from conftest import requires_db
from journal_browser.config import reset_settings_cache
from journal_browser.models import UsageEvent
from journal_browser.services.usage_retention import prune_old_ips

PASSWORD = "test-admin-pw"


# ── Intake ─────────────────────────────────────────────────────────────────


def _page_view(session_id: str = "s1", **kw):
    ev = {
        "type": "page_view",
        "session_id": session_id,
        "path": "/ut/journals/0378-5955",
        "duration_ms": 18342,
        "referrer": "https://example.com/x",
        "ref_type": "journal",
        "ref_id": "0378-5955",
    }
    ev.update(kw)
    return ev


BATCH = {
    "client": {"tz": "Europe/Amsterdam", "locale": "en-GB"},
    "events": [
        _page_view(),
        {
            "type": "search",
            "session_id": "s1",
            "path": "/ut",
            "query": "biochemistry",
            "results_count": 42,
            "search_scope": "journals",
            "filters": {"oa_status": ["gold"]},
        },
        {
            "type": "error",
            "session_id": "s1",
            "path": "/ut",
            "source": "api_status",
            "message": "boom",
            "detail": "GET /api/v1/ut/journals/x 500",
            "status": 500,
        },
    ],
}


@requires_db
async def test_batch_of_three_kinds_enriched(client, db):
    r = await client.post(
        "/api/v1/usage/events",
        json=BATCH,
        headers={
            "X-Forwarded-For": "203.0.113.7, 10.0.0.1",
            "User-Agent": "Mozilla/5.0 (test runner)",
        },
    )
    assert r.status_code == 204
    assert r.content == b""

    rows = (await db.scalars(select(UsageEvent).order_by(UsageEvent.id))).all()
    assert [row.event_type for row in rows] == ["page_view", "search", "error"]
    for row in rows:
        assert str(row.ip) == "203.0.113.7"  # first XFF hop wins
        assert row.user_agent == "Mozilla/5.0 (test runner)"
        assert row.tz == "Europe/Amsterdam"
        assert row.locale == "en-GB"
        assert row.ts is not None

    pv, search, err = rows
    assert pv.duration_ms == 18342
    assert pv.ref_type == "journal"
    assert pv.ref_id == "0378-5955"
    assert pv.referrer == "https://example.com/x"
    assert search.query == "biochemistry"
    assert search.results_count == 42
    assert search.search_scope == "journals"
    assert search.filters == {"oa_status": ["gold"]}
    assert err.source == "api_status"
    assert err.detail == "GET /api/v1/ut/journals/x 500"
    assert err.status == 500


@requires_db
async def test_header_edge_cases(client, db):
    async def _latest_row():
        return (await db.scalars(select(UsageEvent).order_by(UsageEvent.id.desc()).limit(1))).one()

    r = await client.post(
        "/api/v1/usage/events",
        json={"events": [_page_view()]},
        headers={"X-Forwarded-For": "not-an-ip"},
    )
    assert r.status_code == 204
    assert (await _latest_row()).ip is None

    r = await client.post(
        "/api/v1/usage/events",
        json={"events": [_page_view()]},
        headers={"User-Agent": "A" * 600},
    )
    assert r.status_code == 204
    assert (await _latest_row()).user_agent == "A" * 512


@requires_db
async def test_search_browse_normalization(client, db):
    """A missing/blank query is a browse row and never carries query text;
    an explicit browse flag nulls the query too."""
    r = await client.post(
        "/api/v1/usage/events",
        json={
            "events": [
                {"type": "search", "session_id": "s1", "path": "/ut", "query": "  "},
                {"type": "search", "session_id": "s1", "path": "/ut"},
                {
                    "type": "search",
                    "session_id": "s1",
                    "path": "/ut",
                    "query": "gold",
                    "is_browse": True,
                },
                {"type": "search", "session_id": "s1", "path": "/ut", "query": "biochemistry"},
            ]
        },
    )
    assert r.status_code == 204
    rows = (await db.scalars(select(UsageEvent).order_by(UsageEvent.id))).all()
    assert [(row.is_browse, row.query) for row in rows] == [
        (True, None),
        (True, None),
        (True, None),
        (False, "biochemistry"),
    ]


REJECTIONS = [
    pytest.param({"events": [_page_view(f"s{i}") for i in range(101)]}, 422, id="batch-too-large"),
    pytest.param({"events": [_page_view(path="x" * 600)]}, 422, id="path-too-long"),
    pytest.param(
        {"events": [{"type": "click", "session_id": "s1", "path": "/ut"}]},
        422,
        id="unknown-type",
    ),
    pytest.param(
        {"events": [_page_view(ref_type="journal", ref_id=None)]}, 422, id="ref-without-id"
    ),
    pytest.param(
        {"events": [_page_view(ref_id="0378-5955", ref_type=None)]}, 422, id="id-without-ref"
    ),
    pytest.param(
        {
            "events": [
                {
                    "type": "search",
                    "session_id": "s1",
                    "path": "/ut",
                    "filters": {"blob": "x" * 5000},
                }
            ]
        },
        413,
        id="filters-too-large",
    ),
]


@requires_db
@pytest.mark.parametrize(("payload", "status"), REJECTIONS)
async def test_intake_rejections_store_nothing(client, db, payload, status):
    r = await client.post("/api/v1/usage/events", json=payload)
    assert r.status_code == status
    assert (await db.scalars(select(UsageEvent))).all() == []


@requires_db
async def test_flag_off_accepts_and_drops(client, db, monkeypatch):
    monkeypatch.setenv("JB_ENABLE_USAGE_TRACKING", "false")
    reset_settings_cache()
    try:
        r = await client.post("/api/v1/usage/events", json=BATCH)
        assert r.status_code == 204
        assert (await db.scalars(select(UsageEvent))).all() == []
    finally:
        reset_settings_cache()


@requires_db
async def test_prune_old_ips_nulls_only_old_rows(db):
    now = datetime.now(UTC)
    db.add_all(
        [
            UsageEvent(
                session_id="old",
                event_type="page_view",
                path="/ut",
                ip="203.0.113.1",
                country="NL",
                user_agent="ua-old",
                ts=now - timedelta(days=100),
            ),
            UsageEvent(
                session_id="fresh",
                event_type="page_view",
                path="/ut",
                ip="203.0.113.2",
                country="DE",
                user_agent="ua-fresh",
                ts=now,
            ),
        ]
    )
    await db.commit()

    assert await prune_old_ips(db, 90) == 1
    # Raw SELECT: the identity map must not serve pre-UPDATE attribute values.
    rows = (
        await db.execute(
            text("SELECT session_id, host(ip), country, user_agent FROM usage_events ORDER BY id")
        )
    ).all()
    assert rows == [
        ("old", None, "NL", "ua-old"),
        ("fresh", "203.0.113.2", "DE", "ua-fresh"),
    ]


# ── Admin analytics ────────────────────────────────────────────────────────


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
async def test_admin_usage_requires_auth(usage_api):
    assert (await usage_api.get("/api/v1/admin/usage/summary")).status_code == 401
    assert (await usage_api.get("/api/v1/admin/usage/events")).status_code == 401


@requires_db
async def test_admin_summary_aggregates(usage_api, db):
    await _seed(db, "s1", "page_view", path="/ut/journals/0378-5955", duration_ms=1000)
    await _seed(db, "s1", "page_view", path="/ut/journals/0378-5955", duration_ms=3000)
    await _seed(db, "s2", "page_view", path="/ut")
    await _seed(db, "s1", "search", query="biochemistry", results_count=42, search_scope="journals")
    await _seed(db, "s2", "search", query="biochemistry", results_count=0)
    await _seed(db, "s2", "search", is_browse=True)
    await _seed(
        db, "s3", "error", source="api_status", status=500, message="boom", detail="GET /x 500"
    )
    await _seed(db, "s3", "page_view", path="/ut", country="NL", ref_type="journal", ref_id="x")
    await db.commit()

    headers = await _login(usage_api)
    r = await usage_api.get("/api/v1/admin/usage/summary?days=30", headers=headers)
    assert r.status_code == 200
    body = r.json()

    assert body["days"] == 30
    assert body["totals"] == {"page_view": 4, "search": 3, "error": 1}
    assert body["sessions"] == 3
    assert body["searches"] == {"browse": 1, "queries": 2}

    day = body["daily"][-1]
    assert day["page_view"] == 4 and day["search"] == 3 and day["error"] == 1

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
async def test_admin_summary_clamps_days(usage_api, db):
    await _seed(db, "s1", "page_view")
    headers = await _login(usage_api)
    r = await usage_api.get("/api/v1/admin/usage/summary?days=99999", headers=headers)
    assert r.status_code == 200
    assert r.json()["days"] == 365
    r = await usage_api.get("/api/v1/admin/usage/summary?days=0", headers=headers)
    assert r.json()["days"] == 1


@requires_db
async def test_admin_events_page(usage_api, db):
    now = datetime.now(UTC)
    await _seed(db, "s1", "search", query="biochemistry", results_count=42, ts=now)
    await _seed(db, "s2", "search", is_browse=True, ts=now - timedelta(hours=1))
    await _seed(db, "s3", "error", source="api_status", status=500, ts=now - timedelta(days=2))
    await _seed(db, "s4", "page_view", ts=now - timedelta(days=40))
    await db.commit()

    headers = await _login(usage_api)
    r = await usage_api.get("/api/v1/admin/usage/events?days=30", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert [item["session_id"] for item in body["items"]] == ["s1", "s2", "s3"]
    first = body["items"][0]
    assert first["query"] == "biochemistry"
    assert first["is_browse"] is False
    assert first["event_type"] == "search"
    assert body["items"][1]["is_browse"] is True and body["items"][1]["query"] is None

    r = await usage_api.get("/api/v1/admin/usage/events?days=30&event_type=search", headers=headers)
    body = r.json()
    assert body["total"] == 2
    assert [item["event_type"] for item in body["items"]] == ["search", "search"]

    r = await usage_api.get("/api/v1/admin/usage/events?days=30&limit=1&offset=1", headers=headers)
    body = r.json()
    assert body["total"] == 3
    assert [item["session_id"] for item in body["items"]] == ["s2"]

    # days clamps to 365, so the 40-day-old event is inside the window.
    r = await usage_api.get("/api/v1/admin/usage/events?days=99999", headers=headers)
    assert r.json()["total"] == 4

    r = await usage_api.get("/api/v1/admin/usage/events?limit=0", headers=headers)
    assert r.status_code == 422

    # IPs serialize as strings for the admin table.
    r = await usage_api.post(
        "/api/v1/usage/events",
        json={"events": [_page_view("s5", referrer=None, ref_type=None, ref_id=None)]},
        headers={"X-Forwarded-For": "203.0.113.77", "User-Agent": "TestAgent/1.0"},
    )
    assert r.status_code == 204
    r = await usage_api.get("/api/v1/admin/usage/events?event_type=page_view", headers=headers)
    item = r.json()["items"][0]
    assert item["ip"] == "203.0.113.77"
    assert item["user_agent"] == "TestAgent/1.0"
