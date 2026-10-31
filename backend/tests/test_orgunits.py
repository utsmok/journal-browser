"""Org-unit browsing API: faculty/group unions of authors, require_confirmed
gate, deal_works + APC rollups, drop-own-dimension facets, detail bundles,
and institution isolation."""

from urllib.parse import quote

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


@pytest.fixture
async def orgunits_api(db, institution_factory):
    """ut: TNW (Alice 40 works in group Quantum Matter, Bob 5 in Quantum
    Matter, Carol 5 without a group, Dan 4 in Nano Lab) and BMS (Eve 60 in
    Policy Lab); Frank is unconfirmed (hidden by the gate); Hank is
    institute-only (TechMed, no faculty/group). Works w1+w2 sit
    in deal-covered J1 with APC evidence (latest period per doi), w3/w4 in
    uncovered J2. rug: one author, one APC row scoped to rug only."""

    async def _override():
        async with async_sessionmaker(db.bind, expire_on_commit=False)() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    ut = await institution_factory(code="ut")
    rug = await institution_factory(code="rug")
    session = db
    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    session.add(run)
    await session.flush()
    session.add_all(
        [
            journal_factory("1234-5678", publisher_name="Springer", latest_quartile="Q1"),
            journal_factory("2222-2221", publisher_name="Wiley", latest_quartile="Q2"),
        ]
    )
    await session.flush()
    session.add_all(
        [
            JournalFlags(
                institution_id=ut.id, issn_l="1234-5678", works_window_plus=10, deal_covered=True
            ),
            JournalFlags(institution_id=ut.id, issn_l="2222-2221", works_window_plus=8),
        ]
    )

    def _author(
        uuid: str,
        name: str,
        *,
        faculty: str | None,
        group: str | None,
        n_works: int,
        confirmed: bool = True,
        topic: str | None = None,
        orcid: str | None = None,
        institute: str | None = None,
    ) -> Author:
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
            orcid=orcid,
        )

    session.add_all(
        [
            _author(
                "alice-uuid",
                "Alice Author",
                faculty=TNW,
                group="Quantum Matter",
                n_works=40,
                topic="Physics",
                orcid="0000-0002-1111",
                institute="MESA+ Institute",
            ),
            _author(
                "bob-uuid",
                "Bob Builder",
                faculty=TNW,
                group="Quantum Matter",
                n_works=5,
                topic="Chemistry",
            ),
            _author(
                "carol-uuid",
                "Carol Navigator",
                faculty=TNW,
                group=None,
                n_works=5,
                topic="Physics",
            ),
            _author(
                "dan-uuid",
                "Dan Datalab",
                faculty=TNW,
                group="Nano Lab",
                n_works=4,
                topic="Materials",
                institute="MESA+ Institute",
            ),
            _author(
                "hank-uuid",
                "Hank Institute",
                faculty=None,
                group=None,
                institute="TechMed Centre",
                n_works=3,
                topic="Imaging",
            ),
            _author(
                "eve-uuid",
                "Eve Policy",
                faculty=BMS,
                group="Policy Lab",
                n_works=60,
                topic="Governance",
            ),
            _author(
                "frank-uuid",
                "Frank Hidden",
                faculty=TNW,
                group="Secret Group",
                n_works=100,
                confirmed=False,
                topic="Physics",
            ),
            Author(
                institution_id=rug.id,
                pure_uuid="grace-uuid",
                name="Grace Rugged",
                faculty="Science",
                research_group="RUG Lab",
                n_works=7,
                confirmed=True,
                primary_topic="Physics",
            ),
        ]
    )

    def _work(uuid: str, year: int, issn: str, oa: str, doi: str | None) -> Work:
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
            _work("w-1", 2023, "1234-5678", "gold", "10.1/a"),
            _work("w-2", 2024, "1234-5678", "hybrid", "10.1/b"),
            _work("w-3", 2022, "2222-2221", "closed", "10.1/c"),
            _work("w-4", 2021, "2222-2221", "green", None),
        ]
    )
    await session.flush()
    session.add_all(
        [
            AuthorWork(institution_id=ut.id, author_pure_uuid="alice-uuid", work_pure_uuid="w-1"),
            AuthorWork(institution_id=ut.id, author_pure_uuid="alice-uuid", work_pure_uuid="w-2"),
            AuthorWork(institution_id=ut.id, author_pure_uuid="bob-uuid", work_pure_uuid="w-3"),
            AuthorWork(institution_id=ut.id, author_pure_uuid="dan-uuid", work_pure_uuid="w-4"),
        ]
    )
    session.add_all(
        [
            # w-1: latest (2023) period wins over the 2022 row.
            ApcEvidence(
                institution_id=ut.id, doi="10.1/a", period=2022, euro=100, agreement="Elsevier Deal"
            ),
            ApcEvidence(
                institution_id=ut.id, doi="10.1/a", period=2023, euro=120, agreement="Elsevier Deal"
            ),
            # w-2: no agreement label → detail falls back to the journal's publisher.
            ApcEvidence(institution_id=ut.id, doi="10.1/b", period=2024, euro=200, agreement=None),
            # rug-scoped evidence must never leak into ut aggregates.
            ApcEvidence(
                institution_id=rug.id, doi="10.1/a", period=2024, euro=999, agreement="RUG Deal"
            ),
        ]
    )
    await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client, {"ut": ut.id, "rug": rug.id}
    app.dependency_overrides.clear()


@requires_db
async def test_orgunit_faculty_list(orgunits_api):
    client, _ids = orgunits_api
    r = await client.get("/api/v1/ut/orgunits")
    assert r.status_code == 200
    body = r.json()
    assert body["level"] == "faculty"
    assert body["total"] == 2
    assert [i["name"] for i in body["items"]] == [BMS, TNW]  # works desc
    eve, tnw = body["items"]
    assert eve == {
        "level": "faculty",
        "name": BMS,
        "faculty": None,
        "n_authors": 1,
        "n_works": 60,
        "n_groups": 1,
        "deal_works": 0,
        "apc_euro_total": 0.0,
        "apc_n": 0,
        "topics": [{"name": "Governance", "n": 1}],
    }
    assert tnw == {
        "level": "faculty",
        "name": TNW,
        "faculty": None,
        "n_authors": 4,  # Frank (unconfirmed) never aggregates in
        "n_works": 54,  # 40 + 5 + 5 + 4, not Frank's 100
        "n_groups": 2,  # Quantum Matter + Nano Lab
        "deal_works": 2,  # w-1, w-2 in deal-covered J1
        "apc_euro_total": 320.0,  # 120 (latest period) + 200; rug's 999 excluded
        "apc_n": 2,
        "topics": [
            {"name": "Physics", "n": 2},
            {"name": "Chemistry", "n": 1},
            {"name": "Materials", "n": 1},
        ],
    }


@requires_db
async def test_orgunit_group_list_facet_and_filter(orgunits_api):
    client, _ids = orgunits_api
    body = (await client.get("/api/v1/ut/orgunits", params={"level": "group"})).json()
    assert body["level"] == "group"
    assert body["total"] == 3  # Carol has no group; Frank is gated out
    assert [i["name"] for i in body["items"]] == ["Policy Lab", "Quantum Matter", "Nano Lab"]
    quantum = body["items"][1]
    assert quantum == {
        "level": "group",
        "name": "Quantum Matter",
        "faculty": TNW,
        "n_authors": 2,
        "n_works": 45,
        "n_groups": None,
        "deal_works": 2,
        "apc_euro_total": 320.0,
        "apc_n": 2,
        # Equal counts tie alphabetically.
        "topics": [{"name": "Chemistry", "n": 1}, {"name": "Physics", "n": 1}],
    }
    assert body["facets"]["faculty"] == {BMS: 1, TNW: 2}
    # faculty filter (group level only), OR'd over pipe values.
    filtered = (
        await client.get("/api/v1/ut/orgunits", params={"level": "group", "faculty": TNW})
    ).json()
    assert [i["name"] for i in filtered["items"]] == ["Quantum Matter", "Nano Lab"]
    assert filtered["total"] == 2


@requires_db
async def test_orgunit_filters_and_sorts(orgunits_api):
    client, _ids = orgunits_api

    async def names(params: dict) -> list[str]:
        body = (await client.get("/api/v1/ut/orgunits", params=params)).json()
        return [i["name"] for i in body["items"]]

    # Works strata: multi-select OR, unknown strata match nothing. Both
    # faculties land in 50+ (60 and 54 works).
    assert await names({"works": "50+"}) == [BMS, TNW]
    assert await names({"works": "1-4|50+"}) == [BMS, TNW]
    assert await names({"level": "group", "works": "1-4|50+"}) == ["Policy Lab", "Nano Lab"]
    assert await names({"works": "9-12"}) == []
    assert await names({"uses_deals": True}) == [TNW]
    assert await names({"level": "group", "uses_deals": True}) == ["Quantum Matter"]
    # Relevance defaults with q: prefix match first.
    assert await names({"level": "group", "q": "quant"}) == ["Quantum Matter"]
    assert await names({"level": "group", "q": "po"}) == ["Policy Lab"]
    # Explicit sorts.
    assert await names({"sort": "deal_works"}) == [TNW, BMS]
    assert await names({"sort": "name"}) == [BMS, TNW]
    assert await names({"sort": "authors"}) == [TNW, BMS]  # 4 vs 1
    # Pager.
    assert await names({"offset": 1, "limit": 1}) == [TNW]


@requires_db
async def test_orgunit_facets_drop_own_dimension(orgunits_api):
    client, _ids = orgunits_api
    body = (await client.get("/api/v1/ut/orgunits", params={"level": "group"})).json()
    assert body["facets"] == {
        "faculty": {BMS: 1, TNW: 2},
        "size": {"1-4": 1, "5-19": 0, "20-49": 1, "50+": 1},
        "uses_deals": {"yes": 1, "no": 2},
    }

    # The works filter drops its own dimension from the size facet only;
    # the other facets keep it.
    body = (
        await client.get("/api/v1/ut/orgunits", params={"level": "group", "works": "50+"})
    ).json()
    assert body["total"] == 1
    assert body["facets"]["size"] == {"1-4": 1, "5-19": 0, "20-49": 1, "50+": 1}
    assert body["facets"]["faculty"] == {BMS: 1}
    assert body["facets"]["uses_deals"] == {"yes": 0, "no": 1}

    # The uses_deals filter drops its own dimension likewise; the other
    # facets keep it (only Quantum Matter survives the filter).
    body = (
        await client.get("/api/v1/ut/orgunits", params={"level": "group", "uses_deals": True})
    ).json()
    assert body["total"] == 1
    assert body["facets"]["uses_deals"] == {"yes": 1, "no": 2}
    assert body["facets"]["size"] == {"1-4": 0, "5-19": 0, "20-49": 1, "50+": 0}
    assert body["facets"]["faculty"] == {TNW: 1}

    body = (await client.get("/api/v1/ut/orgunits", params={"include_facets": False})).json()
    assert body["facets"] == {}


@requires_db
async def test_orgunit_faculty_detail(orgunits_api):
    client, _ids = orgunits_api
    r = await client.get(f"/api/v1/ut/orgunits/faculty/{quote(TNW)}")
    assert r.status_code == 200
    body = r.json()
    assert body["unit"]["name"] == TNW
    assert body["unit"]["topics"] == [
        {"name": "Physics", "n": 2},
        {"name": "Chemistry", "n": 1},
        {"name": "Materials", "n": 1},
    ]
    # Child groups, works desc.
    assert [g["name"] for g in body["groups"]] == ["Quantum Matter", "Nano Lab"]
    # The unit's venues, distinct works per journal, works desc.
    assert [
        (j["issn_l"], j["n_works"], j["deal_covered"], j["oa_type"], j["quartile"])
        for j in body["journals"]
    ] == [
        ("1234-5678", 2, True, "hybrid", "Q1"),
        ("2222-2221", 2, False, "subscription", "Q2"),
    ]
    # Top authors, works desc, name tiebreak (Bob before Carol at 5).
    assert [(a["pure_uuid"], a["n_works"]) for a in body["authors"]] == [
        ("alice-uuid", 40),
        ("bob-uuid", 5),
        ("carol-uuid", 5),
        ("dan-uuid", 4),
    ]
    assert body["authors"][0]["orcid"] == "0000-0002-1111"
    assert body["authors"][0]["primary_topic"] == "Physics"

    # Unit authors' works per year, newest first, works.oa_status splits.
    def _year(year: int, total: int, **oa: int) -> dict:
        return {
            "year": year,
            "works_count": total,
            "works_count_source": "pure_canon",
            "oa_gold": oa.get("gold", 0),
            "oa_hybrid": oa.get("hybrid", 0),
            "oa_green": oa.get("green", 0),
            "oa_bronze": oa.get("bronze", 0),
            "oa_diamond": oa.get("diamond", 0),
            "oa_closed": oa.get("closed", 0),
        }

    assert body["works_by_year"] == [
        _year(2024, 1, hybrid=1),
        _year(2023, 1, gold=1),
        _year(2022, 1, closed=1),
        _year(2021, 1, green=1),
    ]
    # Deal-covered output: agreement label wins, empty agreement falls back
    # to the journal's publisher; euro from the latest evidence period.
    assert body["deal_usage"] == [
        {"label": "Elsevier Deal", "n_works": 1, "euro": 120.0},
        {"label": "Springer", "n_works": 1, "euro": 200.0},
    ]


@requires_db
async def test_orgunit_group_detail(orgunits_api):
    client, _ids = orgunits_api
    r = await client.get("/api/v1/ut/orgunits/group/Quantum Matter")
    assert r.status_code == 200
    body = r.json()
    assert body["unit"]["name"] == "Quantum Matter"
    assert body["groups"] is None
    # Alice's two J1 works plus Bob's w-3 in J2.
    assert [(j["issn_l"], j["n_works"]) for j in body["journals"]] == [
        ("1234-5678", 2),
        ("2222-2221", 1),
    ]
    assert [(a["pure_uuid"], a["n_works"]) for a in body["authors"]] == [
        ("alice-uuid", 40),
        ("bob-uuid", 5),
    ]
    assert [y["year"] for y in body["works_by_year"]] == [2024, 2023, 2022]
    assert body["deal_usage"] == [
        {"label": "Elsevier Deal", "n_works": 1, "euro": 120.0},
        {"label": "Springer", "n_works": 1, "euro": 200.0},
    ]
    assert (await client.get("/api/v1/ut/orgunits/group/Nope")).status_code == 404
    assert (await client.get("/api/v1/ut/orgunits/faculty/Nope")).status_code == 404


@requires_db
async def test_orgunit_institute_list_and_detail(orgunits_api):
    """Institute level: MESA+ (Alice + Dan) and TechMed (Hank, institute-only
    with no faculty/group) — separate from faculties, own detail bundle."""
    client, _ids = orgunits_api
    body = (await client.get("/api/v1/ut/orgunits", params={"level": "institute"})).json()
    assert body["level"] == "institute"
    assert body["total"] == 2
    assert [i["name"] for i in body["items"]] == ["MESA+ Institute", "TechMed Centre"]
    mesa, techmed = body["items"]
    assert mesa == {
        "level": "institute",
        "name": "MESA+ Institute",
        "faculty": None,
        "n_authors": 2,
        "n_works": 44,  # Alice 40 + Dan 4
        "n_groups": None,
        "deal_works": 2,  # Alice's w-1, w-2
        "apc_euro_total": 320.0,
        "apc_n": 2,
        "topics": [{"name": "Materials", "n": 1}, {"name": "Physics", "n": 1}],
    }
    assert techmed["n_authors"] == 1 and techmed["n_works"] == 3
    assert techmed["faculty"] is None
    # Size strata + deal usage only: no faculty facet at institute level.
    assert body["facets"]["size"] == {"1-4": 1, "5-19": 0, "20-49": 1, "50+": 0}
    assert body["facets"]["uses_deals"] == {"yes": 1, "no": 1}
    assert "faculty" not in body["facets"]

    detail = (await client.get(f"/api/v1/ut/orgunits/institute/{quote('MESA+ Institute')}")).json()
    assert detail["unit"]["name"] == "MESA+ Institute"
    assert detail["groups"] is None
    assert [(a["pure_uuid"], a["n_works"]) for a in detail["authors"]] == [
        ("alice-uuid", 40),
        ("dan-uuid", 4),
    ]
    assert [(j["issn_l"], j["n_works"]) for j in detail["journals"]] == [
        ("1234-5678", 2),
        ("2222-2221", 1),
    ]
    assert [y["year"] for y in detail["works_by_year"]] == [2024, 2023, 2021]
    assert detail["deal_usage"] == [
        {"label": "Elsevier Deal", "n_works": 1, "euro": 120.0},
        {"label": "Springer", "n_works": 1, "euro": 200.0},
    ]
    assert (await client.get("/api/v1/ut/orgunits/institute/Nope")).status_code == 404


@requires_db
async def test_orgunit_institution_isolation(orgunits_api):
    client, _ids = orgunits_api
    body = (await client.get("/api/v1/rug/orgunits")).json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Science"
    assert body["items"][0]["n_works"] == 7
    groups = (await client.get("/api/v1/rug/orgunits", params={"level": "group"})).json()
    assert [i["name"] for i in groups["items"]] == ["RUG Lab"]
    assert (await client.get("/api/v1/nonsense/orgunits")).status_code == 404
