"""Deal register tests: the register is the home-linked deals only."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import requires_db
from journal_browser.models import (
    ApcEvidence,
    Deal,
    DealInstitution,
    DealJournal,
    HarvestRun,
    Institution,
    Journal,
    Publisher,
    Work,
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


@pytest.fixture
async def apc_deals_api(client, db_engine):
    """Two participating deals: one covering a journal with APC evidence,
    one whose effective list has no works at all."""
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async with maker() as session:
        home = Institution(name="University of Twente", code="ut", active=True)
        session.add(home)
        await session.flush()
        run = HarvestRun(source="pure", entity_type="works", config_fingerprint="t")
        session.add(run)
        await session.flush()
        pub = Publisher(name="Springer")
        session.add(pub)
        await session.flush()
        covered_deal = Deal(
            publisher_id=pub.id, esac_id="sn2024ukb", status="current", start_year=2024
        )
        bare_deal = Deal(
            publisher_id=pub.id, esac_id="sn2025bare", status="current", start_year=2025
        )
        session.add_all([covered_deal, bare_deal])
        await session.flush()
        session.add_all(
            [
                DealInstitution(deal_id=covered_deal.id, institution_id=home.id),
                DealInstitution(deal_id=bare_deal.id, institution_id=home.id),
            ]
        )
        covered_journal = Journal(issn_l="1111-1111", title="Covered", type="journal")
        bare_journal = Journal(issn_l="2222-2222", title="Bare", type="journal")
        session.add_all([covered_journal, bare_journal])
        await session.flush()
        session.add_all(
            [
                DealJournal(
                    deal_id=covered_deal.id,
                    issn=covered_journal.issn_l,
                    issn_l=covered_journal.issn_l,
                    source="manual",
                ),
                DealJournal(
                    deal_id=bare_deal.id,
                    issn=bare_journal.issn_l,
                    issn_l=bare_journal.issn_l,
                    source="manual",
                ),
            ]
        )
        session.add(
            Work(
                institution_id=home.id,
                pure_uuid="w-apc",
                doi_normalized="10.1234/apc",
                title="An APC work",
                norm_title="an apc work",
                year=2024,
                journal_issn_l=covered_journal.issn_l,
                first_seen_run=run.id,
                last_seen_run=run.id,
            )
        )
        # Two evidence rows for the one DOI: only the latest period counts.
        session.add_all(
            [
                ApcEvidence(institution_id=home.id, doi="10.1234/apc", period=2023, euro=100.0),
                ApcEvidence(institution_id=home.id, doi="10.1234/apc", period=2024, euro=250.0),
            ]
        )
        await session.commit()
        ids = (covered_deal.id, bare_deal.id)
    return client, ids


@requires_db
async def test_apc_spend_latest_period_per_doi(apc_deals_api):
    client, (covered_id, bare_id) = apc_deals_api
    body = {d["id"]: d for d in (await client.get("/api/v1/ut/deals")).json()}
    # Latest period (2024) wins per DOI; the count is DOIs, not evidence rows.
    assert body[covered_id]["apc_euro_total"] == 250.0
    assert body[covered_id]["apc_n"] == 1
    # Deal whose effective list covers no works: zeros.
    assert body[bare_id]["apc_euro_total"] == 0.0
    assert body[bare_id]["apc_n"] == 0

    detail = (await client.get(f"/api/v1/ut/deals/{covered_id}")).json()
    assert detail["apc_euro_total"] == 250.0
    assert detail["apc_n"] == 1
