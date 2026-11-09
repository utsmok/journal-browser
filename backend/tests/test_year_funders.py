"""Global publication-year filter (year_from/year_to) on the funders
list and funder detail: n_ut_works and top_journals are scoped to the
clamped window via a works join; the list sorts by the scoped counts;
attributes (policy blocks, canon links, the q filter) stay unfiltered;
the default path keeps today's unscoped counts."""

import pytest

from conftest import journal_factory, requires_db
from journal_browser.models import FunderLink, HarvestRun, JiscFunder, Work, WorkFunder

WINDOW_START = 2020
WINDOW_END = 2024
VENUE = "AAAA-AAAA"

#: bare openalex funder id -> {work uuid: year}. F9 stays unlinked: its
#: rows must never surface on any jisc funder item.
WORK_FUNDERS = {
    "F1": {"w1": 2021, "w2": 2023},  # Alpha
    "F2": {"w0": 2020, "w1": 2021},  # Beta
    "F9": {"w9": 2021},  # no funder_links row -> nowhere to show
}

#: jisc funder id -> (name, linked bare openalex id or None).
FUNDERS = {
    701: ("Alpha Foundation", "F1"),
    702: ("Beta Fund", "F2"),
    703: ("Gamma Trust", "F3"),  # linked, zero works
    704: ("Delta House", None),  # unlinked canon row
}


@pytest.fixture
async def funders_api(client, db, institution_factory):
    """ut (window 2020-2024) with jisc funders canon-linked to openalex
    twins whose works span the window edges."""
    ut = await institution_factory(
        code="ut", data_window_start=WINDOW_START, data_window_end=WINDOW_END
    )
    db.add_all(
        JiscFunder(id=fid, name=name, country="NL") for fid, (name, _bare) in FUNDERS.items()
    )
    await db.flush()
    db.add_all(
        FunderLink(
            funder_id=fid,
            source="openalex",
            source_id=f"https://openalex.org/{bare}",
            via="ror",
        )
        for fid, (_name, bare) in FUNDERS.items()
        if bare is not None
    )
    db.add(journal_factory(VENUE))
    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    db.add(run)
    await db.flush()
    uuids = sorted({uuid for rows in WORK_FUNDERS.values() for uuid in rows})
    year_by_uuid = {uuid: year for rows in WORK_FUNDERS.values() for uuid, year in rows.items()}
    db.add_all(
        Work(
            institution_id=ut.id,
            pure_uuid=uuid,
            title=f"Work {uuid}",
            norm_title=f"work {uuid}",
            year=year_by_uuid[uuid],
            work_type="info:eu-repo/semantics/article",
            journal_issn_l=VENUE,
            first_seen_run=run.id,
            last_seen_run=run.id,
        )
        for uuid in uuids
    )
    db.add_all(
        WorkFunder(
            institution_id=ut.id,
            pure_uuid=uuid,
            funder_openalex_id=bare,
            funder_name=f"Funder {bare}",
        )
        for bare, rows in WORK_FUNDERS.items()
        for uuid in rows
    )
    await db.commit()
    return client


def _works_by_name(body: dict) -> dict[str, int]:
    return {item["name"]: item["n_ut_works"] for item in body["items"]}


@requires_db
async def test_default_counts_unscoped(funders_api):
    """No params: today's work_funders-only counts, sorted by count then
    name; unlinked F9 rows leak nowhere."""
    body = (await funders_api.get("/api/v1/ut/funders")).json()
    assert _works_by_name(body) == {
        "Alpha Foundation": 2,
        "Beta Fund": 2,
        "Delta House": 0,
        "Gamma Trust": 0,
    }
    assert [item["name"] for item in body["items"]] == [
        "Alpha Foundation",
        "Beta Fund",
        "Delta House",
        "Gamma Trust",
    ]
    assert body["total"] == 4


@requires_db
async def test_year_scoped_counts_and_order(funders_api):
    """A range joins works on year: counts shrink and the sort follows the
    scoped counts (Beta's two 2020/2021 works outrank Alpha's name)."""
    early = (
        await funders_api.get("/api/v1/ut/funders", params={"year_from": 2020, "year_to": 2021})
    ).json()
    assert _works_by_name(early) == {
        "Beta Fund": 2,
        "Alpha Foundation": 1,
        "Delta House": 0,
        "Gamma Trust": 0,
    }
    assert [item["name"] for item in early["items"]] == [
        "Beta Fund",
        "Alpha Foundation",
        "Delta House",
        "Gamma Trust",
    ]
    late = (await funders_api.get("/api/v1/ut/funders", params={"year_from": 2022})).json()
    assert _works_by_name(late) == {
        "Alpha Foundation": 1,
        "Beta Fund": 0,
        "Delta House": 0,
        "Gamma Trust": 0,
    }


@requires_db
async def test_q_filter_unaffected_by_range(funders_api):
    body = (
        await funders_api.get(
            "/api/v1/ut/funders", params={"q": "beta", "year_from": 2020, "year_to": 2021}
        )
    ).json()
    assert body["total"] == 1
    assert body["items"][0]["n_ut_works"] == 2


@requires_db
async def test_year_params_clamp_to_window(funders_api):
    """The window-covering range and out-of-window bounds reproduce the
    default counts exactly."""
    default = _works_by_name((await funders_api.get("/api/v1/ut/funders")).json())
    wide = _works_by_name(
        (
            await funders_api.get("/api/v1/ut/funders", params={"year_from": 1900, "year_to": 2100})
        ).json()
    )
    below = _works_by_name(
        (await funders_api.get("/api/v1/ut/funders", params={"year_from": 2019})).json()
    )
    assert wide == below == default


@requires_db
async def test_detail_year_scoped(funders_api):
    """Funder detail: n_ut_works and top_journals shrink with the range."""
    default = (await funders_api.get("/api/v1/ut/funders/702")).json()
    assert default["n_ut_works"] == 2
    assert [(j["issn_l"], j["n_works"]) for j in default["top_journals"]] == [(VENUE, 2)]
    early = (
        await funders_api.get("/api/v1/ut/funders/702", params={"year_from": 2020, "year_to": 2021})
    ).json()
    assert early["n_ut_works"] == 2
    assert early["top_journals"][0]["n_works"] == 2
    late = (
        await funders_api.get(
            "/api/v1/ut/funders/702", params={"year_from": 2022, "year_to": WINDOW_END}
        )
    ).json()
    assert late["n_ut_works"] == 0
    assert late["top_journals"] == []
    alpha = (await funders_api.get("/api/v1/ut/funders/701", params={"year_from": 2023})).json()
    assert alpha["n_ut_works"] == 1
    assert [(j["issn_l"], j["n_works"]) for j in alpha["top_journals"]] == [(VENUE, 1)]


@pytest.mark.parametrize("path", ["/api/v1/ut/funders", "/api/v1/ut/funders/701"])
@requires_db
async def test_from_after_to_is_400(funders_api, path):
    response = await funders_api.get(path, params={"year_from": 2023, "year_to": 2021})
    assert response.status_code == 400
