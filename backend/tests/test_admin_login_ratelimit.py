"""Login throttle: after 5 failures per client key (or 50 globally) in a
sliding 15-minute window, /admin/login answers 429 without checking the
password."""

import pytest

from conftest import requires_db
from journal_browser.config import reset_settings_cache
from journal_browser.routers.admin.auth import (
    FAIL_WINDOW_SECONDS,
    MAX_FAILURES_PER_KEY,
    LoginRateLimiter,
    reset_login_limiter,
)

PASSWORD = "rl-admin-pw"


@pytest.fixture
async def rl_api(client, monkeypatch):
    monkeypatch.setenv("JB_ADMIN_PASSWORD", PASSWORD)
    reset_settings_cache()
    reset_login_limiter()
    yield client
    reset_login_limiter()
    reset_settings_cache()


@requires_db
async def test_five_failures_lock_out(rl_api):
    for _ in range(MAX_FAILURES_PER_KEY):
        r = await rl_api.post("/api/v1/admin/login", json={"password": "wrong"})
        assert r.status_code == 403
    # Locked out: even the correct password is refused without a check.
    r = await rl_api.post("/api/v1/admin/login", json={"password": PASSWORD})
    assert r.status_code == 429
    retry_after = int(r.headers["Retry-After"])
    assert 1 <= retry_after <= FAIL_WINDOW_SECONDS


@requires_db
async def test_success_does_not_count(rl_api):
    for _ in range(4):
        assert (
            await rl_api.post("/api/v1/admin/login", json={"password": "wrong"})
        ).status_code == 403
    ok = await rl_api.post("/api/v1/admin/login", json={"password": PASSWORD})
    assert ok.status_code == 200
    # Fifth failure still gets the plain 403; the success consumed nothing.
    assert (await rl_api.post("/api/v1/admin/login", json={"password": "wrong"})).status_code == 403
    assert (await rl_api.post("/api/v1/admin/login", json={"password": "wrong"})).status_code == 429


@requires_db
async def test_client_keys_independent(rl_api):
    for _ in range(MAX_FAILURES_PER_KEY):
        await rl_api.post(
            "/api/v1/admin/login",
            json={"password": "wrong"},
            headers={"X-Forwarded-For": "10.1.1.1"},
        )
    r = await rl_api.post(
        "/api/v1/admin/login", json={"password": PASSWORD}, headers={"X-Forwarded-For": "10.1.1.1"}
    )
    assert r.status_code == 429
    # A different forwarded client still reaches the password check.
    r = await rl_api.post(
        "/api/v1/admin/login", json={"password": "wrong"}, headers={"X-Forwarded-For": "10.1.1.2"}
    )
    assert r.status_code == 403


@requires_db
async def test_fixture_resets_state(rl_api):
    # Earlier tests filled the limiter; the fixture reset means this lone
    # failure is a password 403, not a leftover 429.
    r = await rl_api.post("/api/v1/admin/login", json={"password": "wrong"})
    assert r.status_code == 403


def test_global_limit_blocks_fresh_keys():
    t = 1000.0
    lim = LoginRateLimiter(clock=lambda: t)
    for i in range(50):
        lim.record_failure(f"key{i}")
    assert lim.retry_after("fresh") == FAIL_WINDOW_SECONDS
    # Sliding window: once the failures age out, everything clears.
    t += FAIL_WINDOW_SECONDS + 1
    assert lim.retry_after("fresh") is None


def test_retry_after_ceil_and_expiry():
    t = 0.0
    lim = LoginRateLimiter(clock=lambda: t)
    for _ in range(MAX_FAILURES_PER_KEY):
        lim.record_failure("k")
    t = FAIL_WINDOW_SECONDS - 0.5
    assert lim.retry_after("k") == 1
    t = FAIL_WINDOW_SECONDS + 0.5
    assert lim.retry_after("k") is None
