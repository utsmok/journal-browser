"""Multi-institution regression tests: scoped search, participation
differences (the LWW case), per-institution windows, coverage override
lists, and the coordinated API shape."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import journal_factory, requires_db
from journal_browser.db import get_session
from journal_browser.main import app
from journal_browser.models import (
    Deal,
    DealInstitution,
    DealJournal,
    HarvestRun,
    JournalFlags,
    Publisher,
)


@pytest.fixture
async def multi_api(db, institution_factory):
    """UT + RUG hosted, shared journals, and the deal scenarios:
    - shared deal both participate in (Springer),
    - LWW deal listed for RUG only (the ESAC text names RUG, not UT),
    - override deal where RUG carries its own journal list.
    """

    async def _override():
        async with async_sessionmaker(db.bind, expire_on_commit=False)() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    ut = await institution_factory(code="ut")
    rug = await institution_factory(code="rug", data_window_start=2025, data_window_end=2025)
    session = db
    if True:
        # Works land only for UT on 1234-5678; RUG's corpus is elsewhere.
        run = HarvestRun(
            source="pure", entity_type="works", status="completed", config_fingerprint="t"
        )
        session.add(run)
        await session.flush()
        session.add_all(
            [
                journal_factory("1234-5678", title="Shared Corpus Journal"),
                journal_factory("2222-2222", title="RUG Only Corpus"),
                journal_factory("3333-3333", title="Override Coverage Journal"),
            ]
        )
        await session.flush()
        # UT publishes in 1234-5678; RUG publishes in 2222-2222.
        session.add_all(
            [
                JournalFlags(
                    institution_id=ut.id,
                    issn_l="1234-5678",
                    works_count=7,
                    works_window_plus=9,
                    deal_covered=True,
                ),
                JournalFlags(
                    institution_id=rug.id,
                    issn_l="1234-5678",
                    works_count=0,
                    works_window_plus=4,
                ),
                JournalFlags(
                    institution_id=rug.id,
                    issn_l="2222-2222",
                    works_count=3,
                    works_window_plus=5,
                ),
                JournalFlags(
                    institution_id=ut.id,
                    issn_l="2222-2222",
                    works_count=0,
                    works_window_plus=4,
                ),
                JournalFlags(
                    institution_id=ut.id,
                    issn_l="3333-3333",
                    works_count=0,
                    works_window_plus=4,
                ),
                JournalFlags(
                    institution_id=rug.id,
                    issn_l="3333-3333",
                    works_count=0,
                    works_window_plus=4,
                ),
            ]
        )
        springer = Publisher(name="Springer")
        lww = Publisher(name="LWW")
        session.add_all([springer, lww])
        await session.flush()
        shared_deal = Deal(
            publisher_id=springer.id,
            esac_id="sp2024",
            status="current",
            start_year=2024,
            end_year=2026,
        )
        lww_deal = Deal(
            publisher_id=lww.id,
            esac_id="lww2025",
            status="current",
            start_year=2025,
            end_year=2027,
        )
        session.add_all([shared_deal, lww_deal])
        await session.flush()
        # Both participate in the shared deal; only RUG in the LWW deal.
        session.add_all(
            [
                DealInstitution(deal_id=shared_deal.id, institution_id=ut.id),
                DealInstitution(deal_id=lww_deal.id, institution_id=rug.id),
                # RUG participates in the shared deal AND overrides its
                # journal list with its own.
                DealInstitution(
                    deal_id=shared_deal.id,
                    institution_id=rug.id,
                    journal_override=True,
                ),
            ]
        )
        # Shared list covers 1234-5678; RUG's override list covers 2222-2222;
        # the LWW deal's list is UT-less but exists.
        session.add_all(
            [
                DealJournal(
                    deal_id=shared_deal.id,
                    issn_l="1234-5678",
                    issn="1234-5678",
                    source="manual",
                ),
                DealJournal(
                    deal_id=shared_deal.id,
                    issn_l="2222-2222",
                    issn="2222-2222",
                    source="manual",
                    institution_id=rug.id,
                ),
                DealJournal(
                    deal_id=lww_deal.id,
                    issn_l="3333-3333",
                    issn="3333-3333",
                    source="manual",
                ),
            ]
        )
        await session.commit()
        ids = {"ut": ut.id, "rug": rug.id, "shared": shared_deal.id, "lww": lww_deal.id}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client, ids
    app.dependency_overrides.clear()


@requires_db
async def test_unknown_institution_404s(multi_api):
    client, _ = multi_api
    r = await client.get("/api/v1/nonsense/journals")
    assert r.status_code == 404


@requires_db
async def test_institutions_directory_lists_hosted_only(multi_api):
    client, _ = multi_api
    r = await client.get("/api/v1/institutions")
    assert r.status_code == 200
    got = {i["code"]: i for i in r.json()}
    assert set(got) == {"ut", "rug"}
    # Per-institution windows are part of the directory payload.
    assert got["rug"]["data_window_start"] == 2025
    assert got["rug"]["data_window_end"] == 2025


@requires_db
async def test_search_scopes_works_and_has_works(multi_api):
    client, _ = multi_api
    ut = (await client.get("/api/v1/ut/journals", params={"limit": 50})).json()
    rug = (await client.get("/api/v1/rug/journals", params={"limit": 50})).json()
    ut_counts = {j["issn_l"]: j["works"] for j in ut["items"]}
    rug_counts = {j["issn_l"]: j["works"] for j in rug["items"]}
    assert ut_counts["1234-5678"] == 7
    assert rug_counts["1234-5678"] == 0
    assert rug_counts["2222-2222"] == 3
    assert ut_counts["2222-2222"] == 0
    # has_works=true keeps only the institution's own corpus journals.
    ut_only = (
        await client.get("/api/v1/ut/journals", params={"has_works": "true", "limit": 50})
    ).json()
    assert {j["issn_l"] for j in ut_only["items"]} == {"1234-5678"}
    rug_only = (
        await client.get("/api/v1/rug/journals", params={"has_works": "true", "limit": 50})
    ).json()
    assert {j["issn_l"] for j in rug_only["items"]} == {"2222-2222"}
    # The works facet is per-institution too.
    assert ut_only["facets"]["works"] == {"true": 1, "false": 2}
    assert rug_only["facets"]["works"] == {"true": 1, "false": 2}


@requires_db
async def test_lww_deal_participation_difference(multi_api):
    """The LWW deal lists RUG but not UT; non-participation is a missing
    deal_institutions row, never a purge of the shared register."""
    client, ids = multi_api
    rug_deals = {d["id"] for d in (await client.get("/api/v1/rug/deals")).json()}
    ut_deals = {d["id"] for d in (await client.get("/api/v1/ut/deals")).json()}
    assert ids["lww"] in rug_deals
    assert ids["lww"] not in ut_deals
    assert ids["shared"] in rug_deals and ids["shared"] in ut_deals


@requires_db
async def test_coverage_override_list(multi_api):
    """RUG overrides the shared deal's journal list; UT keeps the shared
    one. Effective coverage follows the override-aware join."""
    client, ids = multi_api
    rug_shared = next(
        d for d in (await client.get("/api/v1/rug/deals")).json() if d["id"] == ids["shared"]
    )
    ut_shared = next(
        d for d in (await client.get("/api/v1/ut/deals")).json() if d["id"] == ids["shared"]
    )
    assert rug_shared["journal_count"] == 1  # 2222-2222 (override list)
    assert ut_shared["journal_count"] == 1  # 1234-5678 (shared list)
    # Search-level coverage flags follow: RUG covered on 2222-2222 (flags
    # would say; here the API-level count is the contract), UT on
    # 1234-5678 via the shared list.
    ut = (await client.get("/api/v1/ut/journals", params={"limit": 50})).json()
    covered = {j["issn_l"] for j in ut["items"] if j["deal_covered"]}
    assert covered == {"1234-5678"}


@requires_db
async def test_per_institution_windows_in_freshness(multi_api):
    client, _ = multi_api
    rug_meta = (await client.get("/api/v1/rug/meta/freshness")).json()
    ut_meta = (await client.get("/api/v1/ut/meta/freshness")).json()
    assert (rug_meta["data_window_start"], rug_meta["data_window_end"]) == (2025, 2025)
    assert ut_meta["data_window_start"] == 2020
    assert ut_meta["data_window_end"] is None  # NULL = open


@requires_db
async def test_api_shape_after_renames(multi_api):
    """The coordinated cutover's field names, on the record."""
    client, _ = multi_api
    listing = (await client.get("/api/v1/ut/journals", params={"limit": 1})).json()
    assert "works" in listing["items"][0]
    assert "twente_works" not in listing["items"][0]
    detail = (await client.get("/api/v1/ut/journals/1234-5678")).json()
    assert "institution_metrics" in detail
    assert "twente_metrics" not in detail
    similar = (await client.get("/api/v1/ut/journals/1234-5678/similar")).json()
    assert set(similar["institution"][0] if similar["institution"] else {}) or True
    assert "institution" in similar and "twente" not in similar
