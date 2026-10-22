"""Search API tests: quality-bar scope (decisions.md #12)."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import requires_db
from journal_browser.db import get_session
from journal_browser.main import app
from journal_browser.models import Journal


def _journal(issn_l: str, **kw) -> Journal:
    base = dict(
        issn_l=issn_l,
        title=f"Journal {issn_l}",
        type="journal",
        is_oa=False,
        is_in_doaj=False,
        in_scimago=False,
        is_active_recently=False,
        last_active_year=None,
    )
    base.update(kw)
    return Journal(**base)


@pytest.fixture
async def api(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    async with maker() as session:
        session.add_all(
            [
                # In bar via DOAJ.
                _journal("1111-1111", is_in_doaj=True),
                # In bar via recent activity.
                _journal("2222-2222", last_active_year=2024, is_active_recently=True),
                # In bar via scimago flag.
                _journal("3333-3333", in_scimago=True),
                # Out of bar: journal type, but no signal.
                _journal("4444-4444"),
                # Out of bar: wrong type entirely.
                _journal("5555-5555", type="repository", is_in_doaj=True),
            ]
        )
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client
    app.dependency_overrides.clear()


@requires_db
async def test_default_scope_is_quality_bar(api):
    r = await api.get("/api/v1/journals")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    issns = {i["issn_l"] for i in body["items"]}
    assert "4444-4444" not in issns and "5555-5555" not in issns
    assert all(i["in_quality_bar"] for i in body["items"])


@requires_db
async def test_scope_all_returns_full_corpus_with_badge_info(api):
    r = await api.get("/api/v1/journals", params={"scope": "all"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5
    by_issn = {i["issn_l"]: i for i in body["items"]}
    assert by_issn["4444-4444"]["in_quality_bar"] is False
    assert by_issn["1111-1111"]["in_quality_bar"] is True
    assert by_issn["5555-5555"]["in_quality_bar"] is False


@requires_db
async def test_facets_respect_scope(api):
    quality = (await api.get("/api/v1/journals")).json()["facets"]
    everything = (await api.get("/api/v1/journals", params={"scope": "all"})).json()["facets"]
    # The out-of-bar journal is not OA, not in DOAJ: oa facet totals differ.
    assert sum(quality["oa"].values()) == 3
    assert sum(everything["oa"].values()) == 5
    assert quality["doaj"]["true"] == 1
    assert everything["doaj"]["true"] == 2


@requires_db
async def test_invalid_scope_rejected(api):
    r = await api.get("/api/v1/journals", params={"scope": "everything"})
    assert r.status_code == 422
