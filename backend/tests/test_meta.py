"""/{code}/meta/freshness serves the institution display block from its row."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import requires_db
from journal_browser.models import Institution


@requires_db
@pytest.fixture
async def meta_api(client, db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async with maker() as session:
        session.add(
            Institution(
                name="University of Twente",
                code="ut",
                active=True,
                short_name="UT",
                ror="https://ror.org/006hf6230",
                library_url="https://lib.example",
                data_window_start=2020,
            )
        )
        await session.commit()
    return client


@pytest.mark.anyio
async def test_freshness_exposes_institution_display_block(meta_api) -> None:
    r = await meta_api.get("/api/v1/ut/meta/freshness")
    assert r.status_code == 200
    settings = r.json()
    assert settings["institution"] == "University of Twente"
    assert settings["institution_short"] == "UT"
    assert settings["ror"] == "https://ror.org/006hf6230"
    assert settings["library_url"] == "https://lib.example"
    # Optional display fields serve the row verbatim: None when unset.
    assert settings["oa_guide_url"] is None
    assert settings["support_email"] is None
    assert settings["research_portal_url"] is None
    # optional personal contact: string or absent, never a stale constant
    assert settings.get("admin_contact") in (None, "") or "@" in settings["admin_contact"]
