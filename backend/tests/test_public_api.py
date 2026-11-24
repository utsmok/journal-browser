"""Public API surface: the filtered reference, per-client rate limits, and
the admin token guard on every admin route."""

import re

import pytest
from httpx import ASGITransport, AsyncClient

from journal_browser.config import reset_settings_cache
from journal_browser.main import app
from journal_browser.ratelimit import WINDOW_SECONDS, RateLimiter, client_ip, limit_group


@pytest.fixture
async def api():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


@pytest.fixture
def limits(monkeypatch):
    def _set(default: int) -> None:
        monkeypatch.setenv("JB_RATE_LIMIT_PER_MINUTE", str(default))
        reset_settings_cache()

    yield _set
    monkeypatch.undo()
    reset_settings_cache()


async def test_public_schema_lists_only_data_routes(api):
    r = await api.get("/api/v1/openapi.json")
    assert r.status_code == 200
    paths = set(r.json()["paths"])
    assert "/api/v1/institutions" in paths
    assert "/api/v1/{institution_code}/journals" in paths
    leaked = [
        p
        for p in paths
        if re.match(r"/api/v1/(admin|feedback|usage|docs|healthz|openapi|api-docs)", p)
    ]
    assert leaked == []
    page = await api.get("/api/v1/api-docs")
    assert page.status_code == 200
    assert "/api/v1/openapi.json" in page.text


async def test_rate_limit_per_client(api, limits):
    limits(3)
    alice = {"X-Forwarded-For": "203.0.113.1"}
    for remaining in (2, 1, 0):
        r = await api.get("/api/v1/openapi.json", headers=alice)
        assert r.status_code == 200
        assert r.headers["RateLimit-Remaining"] == str(remaining)
    r = await api.get("/api/v1/openapi.json", headers=alice)
    assert r.status_code == 429
    assert 1 <= int(r.headers["Retry-After"]) <= WINDOW_SECONDS
    # Another client keeps its own budget, and CF-Connecting-IP wins over
    # the Cloudflare edge address in X-Forwarded-For.
    bob = {"CF-Connecting-IP": "198.51.100.9", "X-Forwarded-For": "203.0.113.1"}
    assert (await api.get("/api/v1/openapi.json", headers=bob)).status_code == 200
    # Internal calls (no forwarding headers, private peer) are never limited.
    assert (await api.get("/api/v1/openapi.json")).status_code == 200


def test_limit_groups():
    assert limit_group("GET", "/api/v1/ut/journals") == "default"
    assert limit_group("GET", "/api/v1/ut/collaborations/partners.csv") == "heavy"
    assert limit_group("GET", "/api/v1/ut/journals/semantic-search") == "heavy"
    assert limit_group("POST", "/api/v1/ut/journals/recommend") == "heavy"
    assert limit_group("GET", "/api/v1/ut/journals/1234-5678/similar") == "heavy"
    assert limit_group("POST", "/api/v1/feedback") == "feedback"
    assert limit_group("OPTIONS", "/api/v1/ut/journals") is None
    assert limit_group("GET", "/ut/journals") is None


async def test_oversized_body_rejected_before_the_app(api):
    r = await api.post(
        "/api/v1/feedback",
        content=b"x" * 2_000_001,
        headers={"X-Forwarded-For": "203.0.113.5", "Content-Type": "application/json"},
    )
    assert r.status_code == 413


def test_limiter_window_resets():
    now = [0.0]
    limiter = RateLimiter(clock=lambda: now[0])
    assert limiter.hit("default", "a", 1) == (0, None)
    assert limiter.hit("default", "a", 1) == (0, WINDOW_SECONDS)
    now[0] = WINDOW_SECONDS
    assert limiter.hit("default", "a", 1) == (0, None)


def test_client_ip_never_falls_back_past_a_bad_header():
    assert client_ip({"x-forwarded-for": "not-an-ip"}, "172.19.0.5") is None
    assert client_ip({"x-forwarded-for": "203.0.113.7, 10.0.0.1"}, None) == "203.0.113.7"
    assert client_ip({}, "10.0.0.2") == "10.0.0.2"


async def test_every_admin_route_but_login_needs_a_token(api, monkeypatch):
    monkeypatch.setenv("JB_ADMIN_PASSWORD", "guard-test-pw")
    reset_settings_cache()
    try:
        admin_routes = [
            (method.upper(), path)
            for path, ops in app.openapi()["paths"].items()
            if path.startswith("/api/v1/admin/") and path != "/api/v1/admin/login"
            for method in ops
        ]
        assert len(admin_routes) > 20
        for method, path in admin_routes:
            url = re.sub(r"\{[^}]+\}", "1", path)
            r = await api.request(method, url, headers={"Authorization": "Bearer 1.forged"})
            assert r.status_code == 401, (method, path, r.status_code)
    finally:
        monkeypatch.delenv("JB_ADMIN_PASSWORD")
        reset_settings_cache()
