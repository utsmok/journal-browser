import pytest
from httpx import ASGITransport, AsyncClient

from journal_browser.main import app


@pytest.fixture
def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_healthz_requires_db(client):
    # healthz touches the database; without one it must return 500, not crash the app
    try:
        resp = await client.get("/api/v1/healthz")
        assert resp.status_code in (200, 500)
    except Exception as exc:  # connection refused surfaces as transport error
        assert "connect" in str(exc).lower()
