"""Deal register tests: the register is the home-linked deals only."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import requires_db
from journal_browser.db import get_session
from journal_browser.main import app
from journal_browser.models import (
    Deal,
    DealInstitution,
    DealJournal,
    Institution,
    Journal,
    Publisher,
)


@pytest.fixture
async def deals_api(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    async with maker() as session:
        home = Institution(name="University of Twente", is_default=True)
        session.add(home)
        await session.flush()
        pub = Publisher(name="Springer")
        other = Publisher(name="Karger")
        session.add_all([pub, other])
        await session.flush()
        twente_deal = Deal(
            publisher_id=pub.id,
            esac_id="sn2024ukb",
            status="current",
            start_year=2024,
            end_year=2026,
        )
        foreign_deal = Deal(
            publisher_id=other.id,
            esac_id="kar2025surf",
            status="current",
            start_year=2025,
            end_year=2027,
            openaccess_nl_url="https://x",
        )
        session.add_all([twente_deal, foreign_deal])
        await session.flush()
        session.add(DealInstitution(deal_id=twente_deal.id, institution_id=home.id))
        # A journal covered by both deals: the panel must show only the
        # home-linked one, even though the other carries openaccess_nl_url.
        journal = Journal(issn_l="1111-1111", title="Shared", type="journal")
        session.add(journal)
        await session.flush()
        session.add_all(
            [
                DealJournal(
                    deal_id=twente_deal.id,
                    issn=journal.issn_l,
                    issn_l=journal.issn_l,
                    source="manual",
                ),
                DealJournal(
                    deal_id=foreign_deal.id,
                    issn=journal.issn_l,
                    issn_l=journal.issn_l,
                    source="manual",
                ),
            ]
        )
        await session.commit()
        ids = (twente_deal.id, foreign_deal.id, journal.issn_l)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client, ids
    app.dependency_overrides.clear()


@requires_db
async def test_listing_has_no_scope_and_lists_the_register(deals_api):
    client, (twente_id, foreign_id, _) = deals_api
    r = await client.get("/api/v1/deals")
    assert r.status_code == 200
    got = {d["id"] for d in r.json()}
    assert {twente_id, foreign_id} <= got
    assert "twente_relevant" not in r.json()[0]
    # Unknown params are ignored; payload equals the plain listing.
    assert {
        d["id"] for d in (await client.get("/api/v1/deals", params={"scope": "home"})).json()
    } == got


@requires_db
async def test_journal_panel_requires_home_link(deals_api):
    client, (_, _, issn) = deals_api
    body = (await client.get(f"/api/v1/journals/{issn}")).json()
    assert len(body["deals"]) == 1
    assert body["deals"][0]["esac_id"] == "sn2024ukb"
