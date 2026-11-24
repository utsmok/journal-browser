"""Security headers on API responses: Next.js sets them only on the pages it
serves, so FastAPI sets its own on everything under /api."""

from httpx import ASGITransport, AsyncClient

from journal_browser.main import app

EXPECTED = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
}


async def test_every_api_response_carries_the_security_headers():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as api:
        responses = [await api.get("/api/v1/openapi.json"), await api.get("/api/v1/no-such-route")]

    assert [r.status_code for r in responses] == [200, 404]
    for response in responses:
        headers = {key: response.headers[key] for key in EXPECTED}
        assert headers == EXPECTED
        # The edge sets HSTS; the API must not add a second, different one.
        assert "strict-transport-security" not in response.headers
