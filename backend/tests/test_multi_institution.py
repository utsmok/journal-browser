"""Multi-institution scoping: isolation between two hosted institutions
on list, facets and detail; the hosted-only institutions directory;
unknown path codes 404; per-institution data windows; and the fresh-deploy
window 0 -> NULL semantics.

Replaces test_multi_institution.py and the data-window essentials of
test_data_windows.py (scenario map: .audit/2026-11-19-sweep/p2-tests-plan.md).
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from conftest import journal_factory, requires_db
from journal_browser.config import Settings
from journal_browser.models import (
    HarvestRun,
    Institution,
    JournalFlags,
    OpenalexWork,
    Work,
)
from journal_browser.services.detail_enrichment import list_works


@pytest.fixture
async def multi_api(client, db, institution_factory):
    """UT (open window) + RUG (2025-2025) hosted; one shared journal plus a
    RUG-side corpus journal with per-institution journal_flags; UT-only
    venue store rows; and two unhosted institution rows (deal participation
    without a code, deactivated with one) that no surface may serve."""
    ut = await institution_factory(code="ut")
    rug = await institution_factory(code="rug", data_window_start=2025, data_window_end=2025)
    db.add(Institution(name="JCT Only University", ror="https://ror.org/jct-only"))
    db.add(
        Institution(name="Retired University", code="old", active=False, ror="https://ror.org/old")
    )
    db.add_all(
        [
            journal_factory("1234-5678", title="Shared Corpus Journal"),
            journal_factory("2222-2222", title="RUG Only Corpus"),
        ]
    )
    await db.flush()
    db.add_all(
        [
            JournalFlags(
                institution_id=ut.id, issn_l="1234-5678", works_count=7, works_window_plus=9
            ),
            JournalFlags(
                institution_id=rug.id, issn_l="1234-5678", works_count=0, works_window_plus=4
            ),
            JournalFlags(
                institution_id=ut.id, issn_l="2222-2222", works_count=0, works_window_plus=4
            ),
            JournalFlags(
                institution_id=rug.id, issn_l="2222-2222", works_count=3, works_window_plus=5
            ),
            # UT's venue store rows for the shared journal; RUG has none.
            OpenalexWork(
                institution_id=ut.id,
                w_id="W1",
                title="One",
                year=2024,
                venue_issn_l="1234-5678",
                cited_by_count=3,
            ),
            OpenalexWork(
                institution_id=ut.id, w_id="W2", title="Two", year=2023, venue_issn_l="1234-5678"
            ),
        ]
    )
    await db.commit()
    return client


@requires_db
async def test_two_institution_isolation(multi_api):
    client = multi_api
    ut = (await client.get("/api/v1/ut/journals", params={"limit": 50})).json()
    rug = (await client.get("/api/v1/rug/journals", params={"limit": 50})).json()
    assert {j["issn_l"]: j["works"] for j in ut["items"]} == {"1234-5678": 7, "2222-2222": 0}
    assert {j["issn_l"]: j["works"] for j in rug["items"]} == {"1234-5678": 0, "2222-2222": 3}

    # has_works keeps only the institution's own corpus; the works facet is
    # per institution over the same corpus.
    ut_only = (await client.get("/api/v1/ut/journals", params={"has_works": "true"})).json()
    rug_only = (await client.get("/api/v1/rug/journals", params={"has_works": "true"})).json()
    assert {j["issn_l"] for j in ut_only["items"]} == {"1234-5678"}
    assert {j["issn_l"] for j in rug_only["items"]} == {"2222-2222"}
    assert ut_only["facets"]["works"] == {"true": 1, "false": 1}
    assert rug_only["facets"]["works"] == {"true": 1, "false": 1}

    # Detail metrics read this institution's store rows only: UT counts its
    # two OpenAlex venue works, RUG's detail of the same journal sees none.
    ut_detail = (await client.get("/api/v1/ut/journals/1234-5678")).json()
    rug_detail = (await client.get("/api/v1/rug/journals/1234-5678")).json()
    assert ut_detail["institution_metrics"]["openalex_matched"] == 2
    assert ut_detail["institution_metrics"]["cited_total"] == 3
    assert rug_detail["institution_metrics"]["openalex_matched"] == 0


@requires_db
async def test_directory_lists_hosted_only(multi_api):
    r = await multi_api.get("/api/v1/institutions")
    assert r.status_code == 200
    got = {i["code"]: i for i in r.json()}
    assert set(got) == {"ut", "rug"}
    # Per-institution windows ride along; NULL end stays null (open).
    assert got["rug"]["data_window_start"] == 2025
    assert got["rug"]["data_window_end"] == 2025
    assert got["ut"]["data_window_end"] is None


@requires_db
async def test_unknown_institution_404s(multi_api):
    client = multi_api
    assert (await client.get("/api/v1/nonsense/journals")).status_code == 404
    assert (await client.get("/api/v1/nonsense/journals/1234-5678")).status_code == 404
    # A known-but-deactivated code is not served either.
    assert (await client.get("/api/v1/old/journals")).status_code == 404


@requires_db
async def test_per_institution_data_windows(multi_api, db, institution_factory):
    client = multi_api
    rug_meta = (await client.get("/api/v1/rug/meta/freshness")).json()
    ut_meta = (await client.get("/api/v1/ut/meta/freshness")).json()
    assert (rug_meta["data_window_start"], rug_meta["data_window_end"]) == (2025, 2025)
    assert (ut_meta["data_window_start"], ut_meta["data_window_end"]) == (2020, None)

    # The works-list query fills an open end with 9999 and a bounded end
    # with the stored year: a far-future work stays listed for the open
    # window and drops for the bounded one.
    ut = (await db.execute(select(Institution).where(Institution.code == "ut"))).scalar_one()
    bounded = await institution_factory(
        code="bounded", data_window_start=2020, data_window_end=2023
    )
    run = HarvestRun(
        source="pure",
        entity_type="works",
        status="completed",
        institution_id=ut.id,
        config_fingerprint="t",
    )
    db.add_all([run, journal_factory("0000-0000")])
    await db.flush()
    db.add_all(
        [
            Work(
                institution_id=ut.id,
                pure_uuid="ut-far",
                title="Far future",
                norm_title="far future",
                year=2030,
                work_type="article",
                journal_issn_l="0000-0000",
                first_seen_run=run.id,
                last_seen_run=run.id,
            ),
            Work(
                institution_id=bounded.id,
                pure_uuid="b-far",
                title="Far future",
                norm_title="far future",
                year=2030,
                work_type="article",
                journal_issn_l="0000-0000",
                first_seen_run=run.id,
                last_seen_run=run.id,
            ),
        ]
    )
    await db.commit()

    open_page = await list_works(db, "0000-0000", ut, page=1, page_size=50)
    bounded_page = await list_works(db, "0000-0000", bounded, page=1, page_size=50)
    assert [i["year"] for i in open_page["items"]] == [2030]
    assert bounded_page["total"] == 0


def test_fresh_deploy_window_zero_means_open():
    """JB_DATA_WINDOW_END=0 is the compose/.env open-ended default; storing
    year 0 would leave every window empty."""
    for raw in (0, "0", ""):
        s = Settings(data_window_end=raw, data_window_start=2020)
        assert s.data_window_end is None
        assert s.window_years
    assert Settings(data_window_end=2025, data_window_start=2020).data_window_end == 2025

    # The institution row carries the same semantics: NULL end runs to the
    # current year, a bounded end is inclusive.
    today = datetime.now(UTC).year
    open_inst = Institution(code="ut", name="UT", data_window_start=today - 2)
    bounded = Institution(
        code="rug", name="RUG", data_window_start=today - 2, data_window_end=today - 1
    )
    assert open_inst.window_years == [today - 2, today - 1, today]
    assert bounded.window_years == [today - 2, today - 1]
