"""/meta/freshness must expose the institution display block from settings."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import requires_db
from journal_browser.db import get_session
from journal_browser.main import app


@requires_db
@pytest.fixture
async def meta_api(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
    app.dependency_overrides.pop(get_session, None)


@pytest.mark.anyio
async def test_freshness_exposes_institution_display_block(meta_api) -> None:
    r = await meta_api.get("/api/v1/meta/freshness")
    assert r.status_code == 200
    settings = r.json()
    assert settings["institution"] == "University of Twente"
    assert settings["institution_short"] == "Twente"
    assert settings["ror"].startswith("https://ror.org/")
    assert settings["library_url"].startswith("https://")
    assert settings["oa_guide_url"].startswith("https://")
    assert "@" in settings["support_email"]
    assert settings["research_portal_url"].startswith("https://")
    # optional personal contact: string or absent, never a stale constant
    assert settings.get("admin_contact") in (None, "") or "@" in settings[
        "admin_contact"
    ]
