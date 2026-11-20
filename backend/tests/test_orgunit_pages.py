"""Org-unit browsing as served: faculty/group/institute lists with exact
item aggregates, drop-own-dimension facets, institution isolation, the
detail bundles (child groups, venues, member authors, works-by-year,
deal-usage labels), the diamond/gold share ordering on the authors card,
resolve_root's ladder over the Pure org tree, the stats zero-budget
gate, and the 32,767-bind regression: a faculty whose roster id set
exceeds asyncpg's bind limit must still serve its gap card (one text[]
bind via = ANY, not a per-id IN-list).
"""

import json
from urllib.parse import quote

import pytest
from sqlalchemy import text

from conftest import journal_factory, requires_db
from journal_browser.harvest.institution_stats import harvest_institution_stats
from journal_browser.harvest.org_closure import resolve_root
from journal_browser.models import (
    ApcEvidence,
    Author,
    AuthorWork,
    HarvestRun,
    Institution,
    JournalFlags,
    OpenalexWork,
    OpenalexWorkAuthor,
    PureOrg,
    Work,
)

TNW = "Faculty of Science and Technology"
BMS = "Faculty of Behavioural, Management and Social Sciences"


@pytest.fixture
async def org_api(client, db, institution_factory):
    """ut: TNW (Alice 40 works in Quantum Matter, Bob 5 in Quantum Matter,
    Carol 5 without a group, Dan 4 in Nano Lab) and BMS (Eve 60 in Policy
    Lab); Frank is unconfirmed (never aggregates); Hank is institute-only
    (TechMed). Works w1+w2 sit in deal-covered J1 with APC evidence (the
    latest period per doi wins), w3/w4 in uncovered J2. rug: one author,
    one APC row scoped to rug only."""
    ut = await institution_factory(code="ut")
    rug = await institution_factory(code="rug")
    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    db.add(run)
    await db.flush()
    db.add_all(
        [
            journal_factory("1234-5678", publisher_name="Springer", latest_quartile="Q1"),
            journal_factory("2222-2221", publisher_name="Wiley", latest_quartile="Q2"),
        ]
    )
    db.add_all(
        [
            JournalFlags(
                institution_id=ut.id, issn_l="1234-5678", works_window_plus=10, deal_covered=True
            ),
            JournalFlags(institution_id=ut.id, issn_l="2222-2221", works_window_plus=8),
        ]
    )

    def _author(uuid, name, *, faculty=None, group=None, n_works=0, confirmed=True, **kw):
        return Author(
            institution_id=ut.id,
            pure_uuid=uuid,
            name=name,
            faculty=faculty,
            research_group=group,
            n_works=n_works,
            confirmed=confirmed,
            **kw,
        )

    db.add_all(
        [
            _author(
                "alice-uuid",
                "Alice Author",
                faculty=TNW,
                group="Quantum Matter",
                n_works=40,
                primary_topic="Physics",
                orcid="0000-0002-1111",
                institute="MESA+ Institute",
            ),
            _author(
                "bob-uuid",
                "Bob Builder",
                faculty=TNW,
                group="Quantum Matter",
                n_works=5,
                primary_topic="Chemistry",
            ),
            _author(
                "carol-uuid", "Carol Navigator", faculty=TNW, n_works=5, primary_topic="Physics"
            ),
            _author(
                "dan-uuid",
                "Dan Datalab",
                faculty=TNW,
                group="Nano Lab",
                n_works=4,
                primary_topic="Materials",
                institute="MESA+ Institute",
            ),
            _author(
                "hank-uuid",
                "Hank Institute",
                institute="TechMed Centre",
                n_works=3,
                primary_topic="Imaging",
            ),
            _author(
                "eve-uuid",
                "Eve Policy",
                faculty=BMS,
                group="Policy Lab",
                n_works=60,
                primary_topic="Governance",
            ),
            _author(
                "frank-uuid",
                "Frank Hidden",
                faculty=TNW,
                group="Secret Group",
                n_works=100,
                confirmed=False,
                primary_topic="Physics",
            ),
            # A unit whose members all lack primary_topic: the detail path
            # used to 500 by indexing the absent topics key.
            _author(
                "no-topic-uuid",
                "Nora Notopic",
                faculty="Faculty of Lost Topics",
                n_works=2,
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

    db.add_all(
        [
            _work("w-1", 2023, "1234-5678", "gold", "10.1/a"),
            _work("w-2", 2024, "1234-5678", "hybrid", "10.1/b"),
            _work("w-3", 2022, "2222-2221", "closed", "10.1/c"),
            _work("w-4", 2021, "2222-2221", "green", None),
        ]
    )
    await db.flush()  # works must exist before the author edges
    db.add_all(
        [
            AuthorWork(institution_id=ut.id, author_pure_uuid="alice-uuid", work_pure_uuid="w-1"),
            AuthorWork(institution_id=ut.id, author_pure_uuid="alice-uuid", work_pure_uuid="w-2"),
            AuthorWork(institution_id=ut.id, author_pure_uuid="bob-uuid", work_pure_uuid="w-3"),
            AuthorWork(institution_id=ut.id, author_pure_uuid="dan-uuid", work_pure_uuid="w-4"),
            # w-1: the latest (2023) evidence period wins over 2022.
            ApcEvidence(
                institution_id=ut.id, doi="10.1/a", period=2022, euro=100, agreement="Elsevier Deal"
            ),
            ApcEvidence(
                institution_id=ut.id, doi="10.1/a", period=2023, euro=120, agreement="Elsevier Deal"
            ),
            # No agreement label: deal usage falls back to the publisher.
            ApcEvidence(institution_id=ut.id, doi="10.1/b", period=2024, euro=200, agreement=None),
            ApcEvidence(
                institution_id=rug.id, doi="10.1/a", period=2024, euro=999, agreement="RUG Deal"
            ),
        ]
    )
    await db.commit()
    return client, {"ut": ut.id, "rug": rug.id}


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


@requires_db
async def test_orgunit_lists_facets_and_isolation(org_api):
    client, _ids = org_api
    body = (await client.get("/api/v1/ut/orgunits")).json()
    assert body["level"] == "faculty"
    assert body["total"] == 3
    # Works desc: Eve (60) before TNW (54), then the topic-less unit (2).
    assert [i["name"] for i in body["items"]] == [BMS, TNW, "Faculty of Lost Topics"]
    assert body["items"][0] == {
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
    assert body["items"][1] == {
        "level": "faculty",
        "name": TNW,
        "faculty": None,
        "n_authors": 4,  # Frank (unconfirmed) never aggregates in
        "n_works": 54,  # 40 + 5 + 5 + 4, not Frank's 100
        "n_groups": 2,  # Quantum Matter + Nano Lab
        "deal_works": 2,  # w-1, w-2 in deal-covered J1
        "apc_euro_total": 320.0,  # 120 (latest period) + 200; rug's 999 out
        "apc_n": 2,
        "topics": [
            {"name": "Physics", "n": 2},
            {"name": "Chemistry", "n": 1},
            {"name": "Materials", "n": 1},
        ],
    }

    # Group level: Carol has no group, Frank is gated out. Equal works
    # counts tie alphabetically (Nano Lab last at 4).
    groups = (await client.get("/api/v1/ut/orgunits", params={"level": "group"})).json()
    assert [i["name"] for i in groups["items"]] == ["Policy Lab", "Quantum Matter", "Nano Lab"]
    assert groups["items"][1] == {
        "level": "group",
        "name": "Quantum Matter",
        "faculty": TNW,
        "n_authors": 2,
        "n_works": 45,
        "n_groups": None,
        "deal_works": 2,
        "apc_euro_total": 320.0,
        "apc_n": 2,
        "topics": [{"name": "Chemistry", "n": 1}, {"name": "Physics", "n": 1}],
    }
    assert groups["facets"] == {
        "faculty": {BMS: 1, TNW: 2},
        "size": {"1-4": 1, "5-19": 0, "20-49": 1, "50+": 1},
        "uses_deals": {"yes": 1, "no": 2},
    }
    # The faculty filter (group level only), OR'd over pipe values.
    filtered = (
        await client.get("/api/v1/ut/orgunits", params={"level": "group", "faculty": TNW})
    ).json()
    assert [i["name"] for i in filtered["items"]] == ["Quantum Matter", "Nano Lab"]

    # Works strata: multi-select OR, unknown strata match nothing.
    works_names = (await client.get("/api/v1/ut/orgunits", params={"works": "1-4|50+"})).json()
    assert [i["name"] for i in works_names["items"]] == [
        BMS,
        TNW,
        "Faculty of Lost Topics",
    ]
    assert [
        i["name"]
        for i in (
            await client.get("/api/v1/ut/orgunits", params={"level": "group", "works": "1-4|50+"})
        ).json()["items"]
    ] == ["Policy Lab", "Nano Lab"]
    assert (await client.get("/api/v1/ut/orgunits", params={"works": "9-12"})).json()["total"] == 0
    # The works filter drops its own dimension from the size facet only.
    wide = (
        await client.get("/api/v1/ut/orgunits", params={"level": "group", "works": "50+"})
    ).json()
    assert wide["total"] == 1
    assert wide["facets"]["size"] == {"1-4": 1, "5-19": 0, "20-49": 1, "50+": 1}
    assert wide["facets"]["faculty"] == {BMS: 1}
    assert wide["facets"]["uses_deals"] == {"yes": 0, "no": 1}
    # The uses_deals filter likewise keeps its own dimension unfiltered.
    deals = (
        await client.get("/api/v1/ut/orgunits", params={"level": "group", "uses_deals": True})
    ).json()
    assert [i["name"] for i in deals["items"]] == ["Quantum Matter"]
    assert deals["facets"]["uses_deals"] == {"yes": 1, "no": 2}
    assert deals["facets"]["size"] == {"1-4": 0, "5-19": 0, "20-49": 1, "50+": 0}
    assert deals["facets"]["faculty"] == {TNW: 1}

    # Institute level: MESA+ (Alice + Dan) and TechMed (Hank alone);
    # no faculty facet there.
    inst = (await client.get("/api/v1/ut/orgunits", params={"level": "institute"})).json()
    assert [i["name"] for i in inst["items"]] == ["MESA+ Institute", "TechMed Centre"]
    mesa = inst["items"][0]
    assert (mesa["n_authors"], mesa["n_works"], mesa["deal_works"]) == (2, 44, 2)
    assert mesa["faculty"] is None and mesa["n_groups"] is None
    assert inst["facets"]["size"] == {"1-4": 1, "5-19": 0, "20-49": 1, "50+": 0}
    assert inst["facets"]["uses_deals"] == {"yes": 1, "no": 1}
    assert "faculty" not in inst["facets"]

    # Institution isolation: rug aggregates only its own author; an
    # unknown code is 404.
    rug_body = (await client.get("/api/v1/rug/orgunits")).json()
    assert [i["name"] for i in rug_body["items"]] == ["Science"]
    assert rug_body["items"][0]["n_works"] == 7
    rug_groups = (await client.get("/api/v1/rug/orgunits", params={"level": "group"})).json()
    assert [i["name"] for i in rug_groups["items"]] == ["RUG Lab"]
    assert (await client.get("/api/v1/nonsense/orgunits")).status_code == 404


@requires_db
async def test_orgunit_detail_bundles(org_api):
    client, _ids = org_api
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
    # The unit's venues: distinct works per journal, works desc.
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
    assert body["works_by_year"] == [
        _year(2024, 1, hybrid=1),
        _year(2023, 1, gold=1),
        _year(2022, 1, closed=1),
        _year(2021, 1, green=1),
    ]
    # Agreement label wins; empty agreement falls back to the journal's
    # publisher; euro comes from the latest evidence period.
    assert body["deal_usage"] == [
        {"label": "Elsevier Deal", "n_works": 1, "euro": 120.0},
        {"label": "Springer", "n_works": 1, "euro": 200.0},
    ]

    group = (await client.get("/api/v1/ut/orgunits/group/Quantum Matter")).json()
    assert group["unit"]["name"] == "Quantum Matter" and group["groups"] is None
    assert [(j["issn_l"], j["n_works"]) for j in group["journals"]] == [
        ("1234-5678", 2),
        ("2222-2221", 1),
    ]
    assert [y["year"] for y in group["works_by_year"]] == [2024, 2023, 2022]
    assert group["deal_usage"] == [
        {"label": "Elsevier Deal", "n_works": 1, "euro": 120.0},
        {"label": "Springer", "n_works": 1, "euro": 200.0},
    ]

    mesa = (await client.get("/api/v1/ut/orgunits/institute/MESA%2B%20Institute")).json()
    assert mesa["unit"]["name"] == "MESA+ Institute" and mesa["groups"] is None
    assert [(a["pure_uuid"], a["n_works"]) for a in mesa["authors"]] == [
        ("alice-uuid", 40),
        ("dan-uuid", 4),
    ]
    assert [y["year"] for y in mesa["works_by_year"]] == [2024, 2023, 2021]

    assert (await client.get("/api/v1/ut/orgunits/group/Nope")).status_code == 404
    assert (await client.get("/api/v1/ut/orgunits/faculty/Nope")).status_code == 404
    assert (await client.get("/api/v1/ut/orgunits/institute/Nope")).status_code == 404

    # Regression: a unit whose members all lack authors.primary_topic used
    # to 500 (the detail path indexed the topics dict directly).
    no_topic = await client.get("/api/v1/ut/orgunits/faculty/Faculty%20of%20Lost%20Topics")
    assert no_topic.status_code == 200
    assert no_topic.json()["unit"]["topics"] == []
    assert [(a["pure_uuid"], a["n_works"]) for a in no_topic.json()["authors"]] == [
        ("no-topic-uuid", 2)
    ]


@pytest.fixture
async def share_api(client, db, institution_factory):
    """ut: group 'OA Leaders' with Dana (4 counted works, 3 diamond/gold
    = 75%), Ted (10 works, 1 diamond = 10%) and Tina (3 works, all
    diamond: below the 4-work minimum, share None)."""
    ut = await institution_factory(code="ut")
    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    db.add(run)
    db.add(journal_factory("3333-3330"))
    await db.flush()
    db.add_all(
        [
            Author(
                institution_id=ut.id,
                pure_uuid="dana-uuid",
                name="Dana Diamond",
                research_group="OA Leaders",
                n_works=4,
                confirmed=True,
            ),
            Author(
                institution_id=ut.id,
                pure_uuid="ted-uuid",
                name="Ted Tenured",
                research_group="OA Leaders",
                n_works=10,
                confirmed=True,
            ),
            Author(
                institution_id=ut.id,
                pure_uuid="tina-uuid",
                name="Tina Trio",
                research_group="OA Leaders",
                n_works=3,
                confirmed=True,
            ),
        ]
    )

    def _work(uuid, year, oa):
        return Work(
            institution_id=ut.id,
            pure_uuid=uuid,
            title=f"Work {uuid}",
            norm_title=f"work {uuid}",
            year=year,
            oa_status=oa,
            journal_issn_l="3333-3330",
            first_seen_run=run.id,
            last_seen_run=run.id,
        )

    works = [
        # Dana: 4 works, 3 diamond/gold.
        *(_work(f"w-d{i}", 2023, oa) for i, oa in [(1, "gold"), (2, "diamond"), (3, "gold")]),
        _work("w-d4", 2022, "closed"),
        # Ted: 10 works, 1 diamond.
        _work("w-t1", 2023, "diamond"),
        *(_work(f"w-t{i}", 2022, "closed") for i in range(2, 11)),
        # Tina: 3 works, all diamond.
        *(_work(f"w-x{i}", 2024, "diamond") for i in range(1, 4)),
    ]
    db.add_all(works)
    await db.flush()
    edges = [
        *(("dana-uuid", f"w-d{i}") for i in range(1, 5)),
        *(("ted-uuid", f"w-t{i}") for i in range(1, 11)),
        *(("tina-uuid", f"w-x{i}") for i in range(1, 4)),
    ]
    db.add_all(
        AuthorWork(institution_id=ut.id, author_pure_uuid=a, work_pure_uuid=w) for a, w in edges
    )
    await db.commit()
    return client


@requires_db
async def test_orgunit_top_authors_share_ordering(share_api):
    """Share ordering (default): a 4-work author at 75% outranks a 10-work
    author at 10%; a 3-work all-diamond author ranks last, share None.
    The works toggle is the previous works-desc behaviour, shares still
    served."""
    url = f"/api/v1/ut/orgunits/group/{quote('OA Leaders')}"
    authors = (await share_api.get(url)).json()["authors"]
    assert [(a["name"], a["n_works"]) for a in authors] == [
        ("Dana Diamond", 4),
        ("Ted Tenured", 10),
        ("Tina Trio", 3),
    ]
    assert [a["oa_diamond_gold_share"] for a in authors] == [0.75, 0.1, None]

    authors = (await share_api.get(url, params={"sort": "works"})).json()["authors"]
    assert [(a["name"], a["n_works"]) for a in authors] == [
        ("Ted Tenured", 10),
        ("Dana Diamond", 4),
        ("Tina Trio", 3),
    ]
    assert [a["oa_diamond_gold_share"] for a in authors] == [0.1, 0.75, None]


@requires_db
async def test_faculty_gap_card_survives_33000_bind_ids(client, db, institution_factory):
    """The faculty route resolves the unit's OpenAlex ids for the gap
    card. 33,000 ids exceed asyncpg's 32,767 bind-argument limit: the =
    ANY single-array form must serve 200; an IN-list regression 500s."""
    ut = await institution_factory(code="ut", data_window_start=2020)
    await db.execute(
        text(
            "INSERT INTO authors"
            " (institution_id, pure_uuid, name, faculty, confirmed, n_works, openalex_ids)"
            " SELECT :iid, 'bulk-' || g, 'Bulk Author ' || g, 'Big Faculty', true, 0,"
            " jsonb_build_array('a' || lpad(g::text, 7, '0'))"
            " FROM generate_series(1, 33000) AS g"
        ),
        {"iid": ut.id},
    )
    db.add(
        OpenalexWork(
            institution_id=ut.id,
            w_id="WBIG",
            title="Bulk Gap Work",
            year=2023,
            venue_issn_l="9999-8888",
            authorships=[{"a": "A0000001", "n": "Bulk Author 1"}],
            source="works_stats",
        )
    )
    await db.flush()  # the work FK must exist before the edge row
    db.add(OpenalexWorkAuthor(institution_id=ut.id, author_id="a0000001", w_id="WBIG"))
    await db.commit()

    r = await client.get("/api/v1/ut/orgunits/faculty/Big%20Faculty")
    assert r.status_code == 200
    body = r.json()
    assert body["unit"]["n_authors"] == 33000
    # The roster ids ride in as one bound array: the gap card resolves
    # the store row attributed to bulk author 1.
    assert body["openalex_only"]["available"] is True
    assert body["openalex_only"]["total"] == 1
    assert body["openalex_only"]["items"][0]["title"] == "Bulk Gap Work"
    assert body["chapter_rollup"]["chapters_total"] == 0


def _inst(name="University of Twente", short="UT"):
    return Institution(name=name, short_name=short)


def _org(uuid, name, org_type="university"):
    return PureOrg(institution_id=1, uuid=uuid, name=name, org_type=org_type)


@pytest.mark.parametrize(
    ("orgs", "parents", "institution", "expected"),
    [
        pytest.param(
            {"root": _org("root", "University of Twente"), "other": _org("other", "Some U")},
            {"other": "root"},
            _inst(),
            "root",
            id="named-root-wins",
        ),
        pytest.param({"root": _org("root", "UT")}, {}, _inst(), "root", id="short-name-match"),
        pytest.param(
            {"root": _org("root", "Some University")},
            {},
            _inst(name="Unrelated"),
            "root",
            id="single-university-fallback",
        ),
        pytest.param(
            {"root": _org("root", "Anything", None)},
            {},
            _inst(name="Unrelated"),
            "root",
            id="single-root-last-resort",
        ),
        pytest.param(
            {
                "b-root": _org("b-root", "University of Twente"),
                "a-root": _org("a-root", "University of Twente"),
                "child": _org("child", "MESA+ Institute", "institute"),
            },
            {"child": "b-root"},
            _inst(),
            "b-root",
            id="duplicates-prefer-children",
        ),
        pytest.param(
            {
                "a-root": _org("a-root", "University of Twente"),
                "b-root": _org("b-root", "University of Twente"),
            },
            {},
            _inst(),
            "a-root",
            id="duplicates-deterministic",
        ),
        pytest.param(
            {"a": _org("a", "Alpha University"), "b": _org("b", "Beta University")},
            {},
            _inst(name="Unrelated"),
            None,
            id="ambiguous-university-roots",
        ),
        pytest.param({}, {}, _inst(), None, id="no-roots"),
    ],
)
def test_resolve_root_ladder(orgs, parents, institution, expected):
    assert resolve_root(orgs, parents, institution) == expected


@requires_db
async def test_stats_skipped_at_zero_budget(db, institution_factory, monkeypatch):
    """The works-filter listing is credit-priced: a budget below the
    reserve must skip the harvest cleanly instead of 429-crashing the
    wave."""

    async def _zero():
        return 0.0

    monkeypatch.setattr("journal_browser.harvest.common.openalex_credits_remaining", _zero)
    inst = await institution_factory()
    stats = await harvest_institution_stats(db, inst)
    assert stats["skipped"] is not None
    json.dumps(stats)  # the job layer prints this verbatim
