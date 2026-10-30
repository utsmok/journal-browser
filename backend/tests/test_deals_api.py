"""Deal register tests: the register is the home-linked deals only."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import requires_db
from journal_browser.models import (
    Deal,
    DealInstitution,
    DealJournal,
    Institution,
    Journal,
    Publisher,
)


@pytest.fixture
async def deals_api(client, db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async with maker() as session:
        home = Institution(name="University of Twente", code="ut", active=True)
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
    return client, ids


@requires_db
async def test_listing_shows_only_participating_deals(deals_api):
    client, (twente_id, foreign_id, _) = deals_api
    r = await client.get("/api/v1/ut/deals")
    assert r.status_code == 200
    got = {d["id"] for d in r.json()}
    # Participation = deal_institutions row: the shared register hides
    # deals this institution is not part of (no purge needed).
    assert got == {twente_id}
    assert foreign_id not in got
    # Unknown params are ignored; payload equals the plain listing.
    assert {
        d["id"] for d in (await client.get("/api/v1/ut/deals", params={"scope": "home"})).json()
    } == got


@requires_db
async def test_journal_panel_requires_home_link(deals_api):
    client, (_, _, issn) = deals_api
    body = (await client.get(f"/api/v1/ut/journals/{issn}")).json()
    assert len(body["deals"]) == 1
    assert body["deals"][0]["esac_id"] == "sn2024ukb"
