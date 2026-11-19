"""Global publication-year filter on the orgunit lists: with an active
range the works-derived columns (n_works, deal_works, n_authors) are
recomputed at query time over the snapshot's edge population — same
author gates (Frank never aggregates), data window replaced by the
clamped range — while the roster and attribute columns (faculty, group
count, APC rollups, topics) stay snapshot. Works sorts, the size strata
filter, size/uses_deals facets and total evaluate the scoped columns;
units without in-range works stay listed at zero; the faculty detail's
child groups inherit the range. No params: byte-identical snapshot
serving."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import journal_factory, requires_db
from journal_browser.db import get_session
from journal_browser.main import app
from journal_browser.models import (
    ApcEvidence,
    Author,
    AuthorWork,
    HarvestRun,
    JournalFlags,
    Work,
)

TNW = "Faculty of Science and Technology"
BMS = "Faculty of Behavioural, Management and Social Sciences"

DEAL = "1234-5678"  # J1, deal-covered
PLAIN = "2222-2221"  # J2


@pytest.fixture
async def org_year_api(db, institution_factory):
    """ut (window 2020-2024): TNW (alice: w1 2021 + w2 2023 in deal J1 and
    w3 2022 in J2; bob: w2; carol: w4 2024 in deal J1) and BMS (eve: w5
    2022 in deal J1); frank is unconfirmed in Quantum Matter with w4.
    APC evidence exists only for w1's doi (2021, outside 2022-2023)."""

    async def _override():
        async with async_sessionmaker(db.bind, expire_on_commit=False)() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    ut = await institution_factory(code="ut", data_window_start=2020, data_window_end=2024)
    session = db
    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    session.add(run)
    await session.flush()
    session.add_all(
        [
            journal_factory(DEAL, publisher_name="Springer", latest_quartile="Q1"),
            journal_factory(PLAIN, publisher_name="Wiley"),
        ]
    )
    await session.flush()
    session.add_all(
        [
            JournalFlags(
                institution_id=ut.id, issn_l=DEAL, works_window_plus=10, deal_covered=True
            ),
            JournalFlags(institution_id=ut.id, issn_l=PLAIN, works_window_plus=8),
        ]
    )

    def _author(uuid, name, *, faculty, group, n_works, confirmed=True, topic=None, institute=None):
        return Author(
            institution_id=ut.id,
            pure_uuid=uuid,
            name=name,
            faculty=faculty,
            research_group=group,
            institute=institute,
            n_works=n_works,
            confirmed=confirmed,
            primary_topic=topic,
        )

    session.add_all(
        [
            _author(
                "alice-uuid",
                "Alice Author",
                faculty=TNW,
                group="Quantum Matter",
                n_works=3,
                topic="Physics",
            ),
            _author(
                "bob-uuid",
                "Bob Builder",
                faculty=TNW,
                group="Quantum Matter",
                n_works=1,
                topic="Chemistry",
            ),
            _author("carol-uuid", "Carol Datalab", faculty=TNW, group="Nano Lab", n_works=1),
            _author("eve-uuid", "Eve Policy", faculty=BMS, group="Policy Lab", n_works=1),
            _author(
                "frank-uuid",
                "Frank Hidden",
                faculty=TNW,
                group="Quantum Matter",
                n_works=1,
                confirmed=False,
            ),
            # Institute-only member: leaves the faculty/group expectations
            # untouched but gives the institute level its own roster.
            _author(
                "hank-uuid",
                "Hank Institute",
                faculty=None,
                group=None,
                n_works=1,
                institute="TechMed Centre",
            ),
        ]
    )

    def _work(uuid, year, issn, oa, doi):
        return Work(
            institution_id=ut.id,
            pure_uuid=uuid,
            title=f"Work {uuid}",
            norm_title=f"work {uuid}",
            year=year,
            oa_status=oa,
            journal_issn_l=issn,
            doi_normalized=doi,
            first_seen_run=run.id,
            last_seen_run=run.id,
        )

    session.add_all(
        [
            _work("w-1", 2021, DEAL, "gold", "10.1/a"),
            _work("w-2", 2023, DEAL, "hybrid", "10.1/b"),
            _work("w-3", 2022, PLAIN, "closed", None),
            _work("w-4", 2024, DEAL, "green", None),
            _work("w-5", 2022, DEAL, "bronze", "10.1/c"),
        ]
    )
    await session.flush()
    session.add_all(
        [
            AuthorWork(institution_id=ut.id, author_pure_uuid="alice-uuid", work_pure_uuid="w-1"),
            AuthorWork(institution_id=ut.id, author_pure_uuid="alice-uuid", work_pure_uuid="w-2"),
            AuthorWork(institution_id=ut.id, author_pure_uuid="alice-uuid", work_pure_uuid="w-3"),
            AuthorWork(institution_id=ut.id, author_pure_uuid="bob-uuid", work_pure_uuid="w-2"),
            AuthorWork(institution_id=ut.id, author_pure_uuid="carol-uuid", work_pure_uuid="w-4"),
            # Frank's edge must never fill a scoped count (confirmed gate).
            AuthorWork(institution_id=ut.id, author_pure_uuid="frank-uuid", work_pure_uuid="w-4"),
            AuthorWork(institution_id=ut.id, author_pure_uuid="eve-uuid", work_pure_uuid="w-5"),
            AuthorWork(institution_id=ut.id, author_pure_uuid="hank-uuid", work_pure_uuid="w-3"),
            # Latest period per doi; 2021 work stays in the APC columns.
            ApcEvidence(institution_id=ut.id, doi="10.1/a", period=2024, euro=50),
        ]
    )
    await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client
    app.dependency_overrides.clear()


def _items(body):
    return {i["name"]: i for i in body["items"]}


@requires_db
async def test_orgunit_list_default_unchanged(org_year_api):
    """No params: the denormalized snapshot answers, exactly the pre-filter
    behavior (n_works = author attribute sums; APC keeps its evidence)."""
    client = org_year_api
    body = (await client.get("/api/v1/ut/orgunits")).json()
    assert body["total"] == 2
    assert [i["name"] for i in body["items"]] == [TNW, BMS]  # works desc
    tnw, bms = body["items"]
    assert tnw == {
        "level": "faculty",
        "name": TNW,
        "faculty": None,
        "n_authors": 3,  # alice, bob, carol; frank never aggregates
        "n_works": 5,  # 3 + 1 + 1 (denormalized sums)
        "n_groups": 2,  # Quantum Matter + Nano Lab
        "deal_works": 3,  # w-1, w-2, w-4 in deal-covered J1
        "apc_euro_total": 50.0,
        "apc_n": 1,
        "topics": [{"name": "Chemistry", "n": 1}, {"name": "Physics", "n": 1}],
    }
    assert bms["n_works"] == 1 and bms["deal_works"] == 1  # w-5
    assert body["facets"] == {
        "size": {"1-4": 1, "5-19": 1, "20-49": 0, "50+": 0},
        "uses_deals": {"yes": 2, "no": 0},
    }
    # And the default stays snapshot-shaped after a scoped call: the live
    # path never writes the cache.
    ranged = (
        await client.get("/api/v1/ut/orgunits", params={"year_from": 2023, "year_to": 2023})
    ).json()
    assert _items(ranged)[TNW]["n_works"] == 1
    again = (await client.get("/api/v1/ut/orgunits")).json()
    assert _items(again)[TNW]["n_works"] == 5


@requires_db
async def test_orgunit_list_counts_year_scoped(org_year_api):
    """Scoped columns come from the range query; attribute columns and the
    roster stay snapshot."""
    client = org_year_api
    body = (
        await client.get("/api/v1/ut/orgunits", params={"year_from": 2022, "year_to": 2023})
    ).json()
    tnw = _items(body)[TNW]
    assert (tnw["n_works"], tnw["deal_works"], tnw["n_authors"]) == (2, 1, 2)  # w-2, w-3
    assert tnw["n_groups"] == 2  # author attribute: stays snapshot
    assert (tnw["apc_euro_total"], tnw["apc_n"]) == (50.0, 1)  # 2021 evidence: stays
    assert tnw["topics"] == [{"name": "Chemistry", "n": 1}, {"name": "Physics", "n": 1}]
    bms = _items(body)[BMS]
    assert (bms["n_works"], bms["deal_works"], bms["n_authors"]) == (1, 1, 1)  # w-5
    # Units without in-range works stay listed at zero (Nano: w-4 is 2024).
    group = (
        await client.get(
            "/api/v1/ut/orgunits", params={"level": "group", "year_from": 2022, "year_to": 2023}
        )
    ).json()
    assert group["total"] == 3
    nano = _items(group)["Nano Lab"]
    assert (nano["n_works"], nano["deal_works"], nano["n_authors"]) == (0, 0, 0)
    quantum = _items(group)["Quantum Matter"]
    assert (quantum["n_works"], quantum["deal_works"], quantum["n_authors"]) == (2, 1, 2)
    assert quantum["apc_euro_total"] == 50.0  # APC rolls up, unfiltered


@requires_db
async def test_orgunit_sorts_year_scoped(org_year_api):
    """authors|works|deal_works sorts evaluate the scoped columns, so the
    same key answers a different order inside a range."""
    client = org_year_api

    async def names(params):
        body = (await client.get("/api/v1/ut/orgunits", params=params)).json()
        return [i["name"] for i in body["items"]]

    group = {"level": "group"}
    assert await names(group) == ["Quantum Matter", "Nano Lab", "Policy Lab"]  # works desc
    scoped = {**group, "year_from": 2022, "year_to": 2023}
    assert await names(scoped) == ["Quantum Matter", "Policy Lab", "Nano Lab"]  # 2/1/0
    assert await names({**group, "sort": "deal_works"}) == [
        "Quantum Matter",
        "Nano Lab",
        "Policy Lab",
    ]  # 2/1/1, ties name-ascending
    assert await names({**scoped, "sort": "deal_works"}) == [
        "Policy Lab",
        "Quantum Matter",
        "Nano Lab",
    ]  # 1/1/0, tie name-ascending: Policy's in-range deal work
    assert await names({**scoped, "sort": "authors", "dir": "asc"}) == [
        "Nano Lab",
        "Policy Lab",
        "Quantum Matter",
    ]  # 0/1/2


@requires_db
async def test_orgunit_facets_year_scoped(org_year_api):
    """Size strata and uses_deals facets re-compute on the scoped columns;
    the faculty facet keeps the snapshot attribute counts."""
    client = org_year_api
    default = (await client.get("/api/v1/ut/orgunits", params={"level": "group"})).json()
    assert default["facets"] == {
        "faculty": {BMS: 1, TNW: 2},
        "size": {"1-4": 3, "5-19": 0, "20-49": 0, "50+": 0},
        "uses_deals": {"yes": 3, "no": 0},
    }
    scoped = (
        await client.get(
            "/api/v1/ut/orgunits",
            params={"level": "group", "year_from": 2022, "year_to": 2023},
        )
    ).json()
    assert scoped["facets"] == {
        "faculty": {BMS: 1, TNW: 2},  # attribute: unchanged
        "size": {"1-4": 2, "5-19": 0, "20-49": 0, "50+": 0},  # Nano drops out
        "uses_deals": {"yes": 2, "no": 1},
    }
    only2023 = (
        await client.get(
            "/api/v1/ut/orgunits",
            params={"level": "group", "year_from": 2023, "year_to": 2023},
        )
    ).json()
    assert only2023["facets"]["uses_deals"] == {"yes": 1, "no": 2}  # w-2 only


@requires_db
async def test_orgunit_filters_and_total_year_scoped(org_year_api):
    """The works strata filter and uses_deals filter evaluate the scoped
    columns, so the same filter answers a different total."""

    async def names(params):
        body = (await client.get("/api/v1/ut/orgunits", params=params)).json()
        return body["total"], [i["name"] for i in body["items"]]

    client = org_year_api
    # Default: TNW's 5 works sit in 5-19, BMS's single work in 1-4.
    assert await names({"works": "1-4"}) == (1, [BMS])
    assert await names({"works": "5-19"}) == (1, [TNW])
    # Scoped to 2021 both faculties hold exactly one work (w-1).
    scoped = {"year_from": 2021, "year_to": 2021}
    assert await names({**scoped, "works": "1-4"}) == (1, [TNW])
    assert await names({**scoped, "works": "5-19"}) == (0, [])
    # uses_deals=true keeps only units with in-range deal works.
    assert await names({"uses_deals": True}) == (2, [TNW, BMS])
    assert await names({"year_from": 2023, "uses_deals": True}) == (1, [TNW])


@requires_db
async def test_orgunit_year_params_clamp_to_window(org_year_api):
    """1900/2100 clamps into the 2020-2024 window; counts stay
    distinct-per-unit (shared works count once; Frank's edge is gated)."""
    client = org_year_api

    async def scoped(params):
        body = (await client.get("/api/v1/ut/orgunits", params={"level": "group", **params})).json()
        return {n: (i["n_works"], i["deal_works"], i["n_authors"]) for n, i in _items(body).items()}

    wide = await scoped({"year_from": 1900, "year_to": 2100})
    assert wide == await scoped({"year_from": 2020, "year_to": 2024})
    assert wide == {
        # w-1, w-2, w-3 (alice+bob share w-2); frank's w-4 stays gated out
        "Quantum Matter": (3, 2, 2),
        "Nano Lab": (1, 1, 1),  # w-4
        "Policy Lab": (1, 1, 1),  # w-5
    }


@requires_db
async def test_orgunit_institute_list_year_scoped(org_year_api):
    """The institute level scopes the same way (its key is the author's
    institute attribute); members without in-range works stay at zero."""
    client = org_year_api
    default = (await client.get("/api/v1/ut/orgunits", params={"level": "institute"})).json()
    assert default["total"] == 1
    techmed = _items(default)["TechMed Centre"]
    assert (techmed["n_works"], techmed["deal_works"], techmed["n_authors"]) == (1, 0, 1)  # w-3
    scoped = (
        await client.get("/api/v1/ut/orgunits", params={"level": "institute", "year_from": 2023})
    ).json()
    assert scoped["total"] == 1  # still listed
    assert (
        _items(scoped)["TechMed Centre"]["n_works"],
        _items(scoped)["TechMed Centre"]["deal_works"],
        _items(scoped)["TechMed Centre"]["n_authors"],
    ) == (0, 0, 0)  # w-3 is 2022


@requires_db
async def test_orgunit_from_after_to_is_400(org_year_api):
    client = org_year_api
    response = await client.get("/api/v1/ut/orgunits", params={"year_from": 2023, "year_to": 2021})
    assert response.status_code == 400


@requires_db
async def test_orgunit_detail_groups_year_scoped(org_year_api):
    """The faculty detail's child groups inherit the range: same scoped
    columns and ordering as the groups list."""
    client = org_year_api

    async def group_rows(params):
        body = (await client.get(f"/api/v1/ut/orgunits/faculty/{TNW}", params=params)).json()
        return [(g["name"], g["n_works"], g["deal_works"]) for g in body["groups"]]

    assert await group_rows(None) == [
        ("Quantum Matter", 4, 2),
        ("Nano Lab", 1, 1),
    ]
    assert await group_rows({"year_from": 2022, "year_to": 2023}) == [
        ("Quantum Matter", 2, 1),
        ("Nano Lab", 0, 0),
    ]
