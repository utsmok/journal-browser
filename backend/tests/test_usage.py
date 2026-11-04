"""Usage tracking: batch intake, flag gate, validation caps, enrichment."""

import pytest
from sqlalchemy import select

from conftest import requires_db
from journal_browser.config import reset_settings_cache
from journal_browser.models import UsageEvent


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
async def test_bad_xff_yields_null_ip(client, db):
    r = await client.post(
        "/api/v1/usage/events",
        json={"events": [_page_view()]},
        headers={"X-Forwarded-For": "not-an-ip"},
    )
    assert r.status_code == 204
    row = (await db.scalars(select(UsageEvent))).one()
    assert row.ip is None


@requires_db
async def test_user_agent_truncated_to_512(client, db):
    r = await client.post(
        "/api/v1/usage/events",
        json={"events": [_page_view()]},
        headers={"User-Agent": "A" * 600},
    )
    assert r.status_code == 204
    row = (await db.scalars(select(UsageEvent))).one()
    assert row.user_agent == "A" * 512


@requires_db
async def test_over_100_events_rejected(client, db):
    r = await client.post(
        "/api/v1/usage/events", json={"events": [_page_view(f"s{i}") for i in range(101)]}
    )
    assert r.status_code == 422


@requires_db
async def test_oversized_path_rejected(client, db):
    r = await client.post("/api/v1/usage/events", json={"events": [_page_view(path="x" * 600)]})
    assert r.status_code == 422


@requires_db
async def test_oversized_filters_rejected_413(client):
    r = await client.post(
        "/api/v1/usage/events",
        json={
            "events": [
                {
                    "type": "search",
                    "session_id": "s1",
                    "path": "/ut",
                    "filters": {"blob": "x" * 5000},
                }
            ]
        },
    )
    assert r.status_code == 413


@requires_db
async def test_search_browse_normalization(client, db):
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
async def test_bad_event_type_rejected(client):
    r = await client.post(
        "/api/v1/usage/events",
        json={"events": [{"type": "click", "session_id": "s1", "path": "/ut"}]},
    )
    assert r.status_code == 422


@pytest.mark.parametrize("pair", [{"ref_type": "journal"}, {"ref_id": "0378-5955"}])
async def test_half_ref_pair_rejected(client, pair):
    ev = {"type": "page_view", "session_id": "s1", "path": "/ut", **pair}
    r = await client.post("/api/v1/usage/events", json={"events": [ev]})
    assert r.status_code == 422
