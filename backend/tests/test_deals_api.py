"""Deals register tests: scope=home shows only Twente-linked deals."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import requires_db
from journal_browser.db import get_session
from journal_browser.main import app
from journal_browser.models import Deal, DealInstitution, Institution, Publisher


@pytest.fixture
async def deals_api(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    async with maker() as session:
        home = Institution(name="University of Twente", is_home=True)
        session.add(home)
        await session.flush()
        pub = Publisher(name="Springer")
        other = Publisher(name="Karger")
        session.add_all([pub, other])
        await session.flush()
        twente_deal = Deal(
            publisher_id=pub.id, esac_id="sn2024ukb", status="current",
            start_year=2024, end_year=2026,
        )
        foreign_deal = Deal(
            publisher_id=other.id, esac_id="kar2025surf", status="current",
            start_year=2025, end_year=2027, openaccess_nl_url="https://x",
        )
        session.add_all([twente_deal, foreign_deal])
        await session.flush()
        session.add(DealInstitution(deal_id=twente_deal.id, institution_id=home.id))
        await session.commit()
        ids = (twente_deal.id, foreign_deal.id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client, ids
    app.dependency_overrides.clear()


@requires_db
async def test_home_scope_lists_only_twente_deals(deals_api):
    client, (twente_id, foreign_id) = deals_api
    body = (await client.get("/api/v1/deals", params={"scope": "home"})).json()
    got = {d["id"] for d in body}
    assert twente_id in got
    assert foreign_id not in got


@requires_db
async def test_all_scope_still_lists_foreign_deals(deals_api):
    client, (twente_id, foreign_id) = deals_api
    body = (await client.get("/api/v1/deals", params={"scope": "all"})).json()
    got = {d["id"] for d in body}
    assert {twente_id, foreign_id} <= got


@requires_db
async def test_twente_relevant_flag_matches_link(deals_api):
    client, (twente_id, foreign_id) = deals_api
    body = (await client.get("/api/v1/deals", params={"scope": "all"})).json()
    flags = {d["id"]: d["twente_relevant"] for d in body}
    assert flags[twente_id] is True
    assert flags[foreign_id] is False
