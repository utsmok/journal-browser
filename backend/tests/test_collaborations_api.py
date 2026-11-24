"""Collaboration partners API: works (not links) are what gets counted,
filters narrow works, partners and links, each facet keeps every other
filter, and the detail, map and CSV exports agree with the list."""

from datetime import UTC, datetime

import pytest

from conftest import requires_db
from journal_browser.models import (
    Author,
    AuthorWork,
    FunderAlias,
    HarvestRun,
    OpenaireWorkFacts,
    PartnerInstitution,
    Work,
    WorkFunder,
    WorkPartner,
    WorkPureAuthor,
)

P1, P2, P3 = "01a2b3c04", "02b3c4d05", "03c4d5e06"

# (work, partner, payload that supplied the link, corresponding author,
# author positions held at the partner)
LINKS = (
    ("w1", P1, "openalex", True, 2),
    ("w1", P2, "openaire", False, 1),
    ("w2", P1, "openalex", False, 1),
    ("w3", P3, "openaire", False, 3),
    ("w4", P1, "openalex", False, 1),
    ("w7", P1, "openalex", False, 1),
    ("w8", P1, "openalex", False, 1),
)


@pytest.fixture
async def collab_api(client, db, institution_factory):
    """ut (window 2020 onward) with works w1..w6 in 2020..2025, author a1
    (faculty ET) on w1, w2, w3 and author a2 (faculty EWI) on w4. Links as
    in LINKS: w5 and w6 have no partner, w1 reaches two partners, and w7
    (retired) and w8 (a dataset) link to P1 and stay out of every count."""
    ut = await institution_factory(code="ut", data_window_start=2020)
    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    db.add(run)
    await db.flush()

    def work(n: int, work_type: str = "info:eu-repo/semantics/article") -> Work:
        return Work(
            institution_id=ut.id,
            pure_uuid=f"w{n}",
            title=f"Work {n}",
            norm_title=f"work {n}",
            year=2019 + n,
            doi_normalized=f"10.0/w{n}",
            work_type=work_type,
            first_seen_run=run.id,
            last_seen_run=run.id,
        )

    retired = work(7)
    retired.retired_at = datetime(2025, 1, 1, tzinfo=UTC)
    db.add_all([*(work(n) for n in range(1, 7)), work(8, "dataset"), retired])
    db.add_all(
        [
            Author(
                institution_id=ut.id,
                pure_uuid="a1",
                name="Test Author",
                faculty="ET",
                confirmed=True,
            ),
            Author(
                institution_id=ut.id,
                pure_uuid="a2",
                name="Second Author",
                faculty="EWI",
                confirmed=True,
            ),
        ]
    )
    await db.flush()
    db.add_all(
        AuthorWork(institution_id=ut.id, author_pure_uuid=author, work_pure_uuid=w)
        for author, works in (("a1", ("w1", "w2", "w3")), ("a2", ("w4",)))
        for w in works
    )
    db.add_all(
        WorkPureAuthor(
            institution_id=ut.id,
            work_pure_uuid=w,
            person_uuid="a1",
            position=1,
            first_names="Test",
            family_names="Author",
        )
        for w in ("w1", "w2", "w3")
    )
    db.add_all(
        [
            WorkFunder(
                institution_id=ut.id,
                pure_uuid="w1",
                funder_openalex_id="F1",
                funder_name="Alpha Foundation",
                award="A1",
            ),
            WorkFunder(
                institution_id=ut.id,
                pure_uuid="w2",
                funder_openalex_id="F1",
                funder_name="Alpha Foundation",
            ),
            # Both payloads credit w4 with F2: OpenAlex by id, OpenAIRE by
            # the name funder_aliases resolves.
            WorkFunder(
                institution_id=ut.id,
                pure_uuid="w4",
                funder_openalex_id="F2",
                funder_name="Beta Fund",
            ),
            WorkFunder(
                institution_id=ut.id,
                pure_uuid="w3",
                funder_openalex_id="F2",
                funder_name="Beta Fund",
                award="B1",
            ),
        ]
    )
    db.add_all(
        [
            OpenaireWorkFacts(
                institution_id=ut.id,
                pure_uuid="w1",
                source_pk="oai:w1",
                projects=[
                    {
                        "id": "p1",
                        "funder": "European Commission",
                        "code": "812345",
                        "acronym": "PROJ",
                    }
                ],
            ),
            OpenaireWorkFacts(
                institution_id=ut.id,
                pure_uuid="w4",
                source_pk="oai:w4",
                projects=[{"id": "p2", "funder": "NWO"}],
            ),
            FunderAlias(funder_name="NWO", funder_openalex_id="F2", rule="grant", works=3),
        ]
    )
    db.add_all(
        [
            PartnerInstitution(
                ror=P1,
                name="Alpha University",
                org_type="education",
                country_code="NL",
                city="Enschede",
                lat=52.2,
                lng=6.9,
                status="active",
                openalex_id="I1",
                search_text="alpha university | enschede | au | 01a2b3c04",
                acronyms=["au"],
                payload={
                    "names": [
                        {"value": "AU", "types": ["acronym"]},
                        {"value": "Alpha University", "types": ["ror_display"]},
                        {"value": "Alpha University", "types": ["label"]},
                    ],
                    "links": [
                        {"type": "wikidata", "value": "Q1"},
                        {"type": "homepage", "value": "https://alpha.example"},
                    ],
                    "relationships": [
                        {
                            "type": "related",
                            "id": "https://ror.org/02b3c4d05",
                            "label": "Beta Institute",
                        }
                    ],
                },
            ),
            PartnerInstitution(
                ror=P2,
                name="Beta Institute",
                org_type="nonprofit",
                country_code="DE",
                search_text="beta institute | 02b3c4d05",
            ),
            PartnerInstitution(
                ror=P3,
                name="Alpha College",
                org_type="education",
                country_code="US",
                lat=41.0,
                lng=-74.0,
                search_text="alpha college | 03c4d5e06",
            ),
        ]
    )
    await db.flush()
    db.add_all(
        WorkPartner(
            institution_id=ut.id,
            work_pure_uuid=w,
            partner_ror=ror,
            source=source,
            corresponding=corresponding,
            authorships=authorships,
        )
        for w, ror, source, corresponding, authorships in LINKS
    )
    await db.commit()
    return ut


async def search(client, **params) -> dict:
    response = await client.get("/api/v1/ut/collaborations", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def rors(client, **params) -> list[str]:
    return [item["ror"] for item in (await search(client, **params))["items"]]


@requires_db
async def test_counts_are_works_not_links(client, collab_api):
    body = await search(client, include_credits=True)
    assert (body["total_works"], body["works_with_partner"], body["total_partners"]) == (6, 4, 3)
    assert body["works_by_source"] == {"openalex": 3, "openaire": 2}
    assert (body["year_from"], body["year_to"]) == (2020, 2025)
    p1, p3, p2 = body["items"]
    # w1 reaches P1 and P2: it counts once in works_with_partner.
    assert (p1["ror"], p1["works"], p1["corresponding_works"], p1["share"]) == (P1, 3, 1, 0.5)
    assert (p1["authorships"], p3["authorships"], p2["authorships"]) == (4, 3, 1)
    assert p1["sources"] == ["openalex"]
    # F2 is one funder credited by both payloads on w4, and w4 counts once.
    assert [(f["key"], f["sources"], f["works"]) for f in p1["funders"]] == [
        ("openalex:F1", ["openalex"], 2),
        ("openalex:F2", ["openaire", "openalex"], 1),
        ("openaire:European Commission", ["openaire"], 1),
    ]
    assert [(p["key"], p["works"]) for p in p1["projects"]] == [
        ("openalex:F1/A1", 1),
        ("openaire:p1", 1),
        ("openaire:p2", 1),
    ]
    # Default list skips per-row credits for speed.
    fast = await search(client)
    assert fast["items"][0]["funders"] == []
    assert fast["items"][0]["projects"] == []
    # P3 and P2 tie on works; the name breaks the tie.
    assert (p3["ror"], p2["ror"]) == (P3, P2)
    # P2's one joint work is w1, so it shares w1's funders.
    assert [(f["key"], f["works"]) for f in p2["funders"]] == [
        ("openalex:F1", 1),
        ("openaire:European Commission", 1),
    ]
    assert p2["in_ror"] is False and p1["in_ror"] is True


@requires_db
async def test_facets_count_works_and_keep_the_other_filters(client, collab_api):
    facets = (await search(client))["facets"]
    assert [(f["value"], f["count"]) for f in facets["org_type"]] == [
        ("education", 4),
        ("nonprofit", 1),
    ]
    assert [(f["value"], f["count"]) for f in facets["country"]] == [
        ("NL", 3),
        ("DE", 1),
        ("US", 1),
    ]
    assert [(f["value"], f["count"]) for f in facets["orgunit"]] == [("ET", 3), ("EWI", 1)]
    assert [(f["value"], f["count"]) for f in facets["source"]] == [
        ("openalex", 3),
        ("openaire", 2),
    ]
    assert [(f["key"], f["works"]) for f in facets["funder"]] == [
        ("openalex:F1", 2),
        ("openalex:F2", 2),
        ("openaire:European Commission", 1),
    ]
    assert [(p["key"], p["code"], p["acronym"], p["funder"]) for p in facets["project"]] == [
        ("openalex:F1/A1", "A1", None, "Alpha Foundation"),
        ("openalex:F2/B1", "B1", None, "Beta Fund"),
        ("openaire:p1", "812345", "PROJ", "European Commission"),
        ("openaire:p2", None, None, "NWO"),
    ]
    # A facet leaves its own filter open and keeps the faculty filter.
    narrowed = (await search(client, type="nonprofit", faculty="ET"))["facets"]
    assert [(f["value"], f["count"]) for f in narrowed["org_type"]] == [
        ("education", 3),
        ("nonprofit", 1),
    ]


@requires_db
async def test_filters_narrow_works_partners_and_links(client, collab_api):
    body = await search(client, level="faculty", faculty="ET")
    assert (body["total_works"], body["works_with_partner"]) == (3, 3)
    assert [(i["ror"], i["works"], i["share"]) for i in body["items"]] == [
        (P1, 2, 0.6667),
        (P3, 1, 0.3333),
        (P2, 1, 0.3333),
    ]
    assert await rors(client, level="faculty", faculty="EWI") == [P1]

    body = await search(client, year_from=2021, year_to=2022)
    assert (body["total_works"], body["year_from"], body["year_to"]) == (2, 2021, 2022)
    assert [i["works"] for i in body["items"]] == [1, 1]

    assert await rors(client, q="alpha") == [P1, P3]
    # Exact acronym and city searches match ROR aliases and locations.
    assert await rors(client, q="AU") == [P1]
    assert await rors(client, q="Enschede") == [P1]
    assert await rors(client, q=P2) == [P2]
    assert await rors(client, country="de") == [P2]
    assert await rors(client, type="nonprofit") == [P2]
    assert await rors(client, type="nonprofit", include_facets=False) == [P2]

    # The payload filter keeps the work set and drops the other links.
    body = await search(client, source="openaire")
    assert (body["total_works"], body["works_with_partner"]) == (6, 2)
    assert [i["ror"] for i in body["items"]] == [P3, P2]

    # Funders and projects come from OpenAlex awards and OpenAIRE projects.
    body = await search(client, funder="openalex:F1")
    assert (body["total_works"], body["works_with_partner"]) == (2, 2)
    # OpenAIRE credits "NWO" and OpenAlex F2; funder_aliases makes them one
    # funder, so the key of either payload selects both payloads' works.
    body = await search(client, funder="openalex:F2")
    assert (body["total_works"], sorted(i["ror"] for i in body["items"])) == (2, [P1, P3])
    body = await search(client, funder="openaire:European Commission")
    assert [i["ror"] for i in body["items"]] == [P1, P2]
    assert (
        body["total_works"],
        body["items"][0]["works"],
        body["items"][0]["corresponding_works"],
    ) == (1, 1, 1)
    assert await rors(client, project="openalex:F1/A1") == [P1, P2]
    assert await rors(client, project="openaire:p2") == [P1]


@requires_db
async def test_sort_and_paging(client, collab_api):
    assert await rors(client, sort="name", dir="asc") == [P3, P1, P2]
    assert await rors(client, sort="name", dir="desc") == [P2, P1, P3]
    assert await rors(client, sort="corresponding_works", dir="desc") == [P1, P3, P2]
    body = await search(client, limit=1, offset=1)
    assert (body["total_partners"], [i["ror"] for i in body["items"]]) == (3, [P3])


@requires_db
async def test_map_leaves_out_partners_without_coordinates(client, collab_api):
    response = await client.get("/api/v1/ut/collaborations/map")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["unmapped"] == 1
    # The organisation type colours the map circles.
    assert sorted(
        (p["ror"], p["country_code"], p["org_type"], p["works"]) for p in body["items"]
    ) == [
        (P1, "NL", "education", 3),
        (P3, "US", "education", 1),
    ]
    filtered = (
        await client.get("/api/v1/ut/collaborations/map", params={"type": "nonprofit"})
    ).json()
    assert filtered == {"items": [], "unmapped": 1}


@requires_db
async def test_detail(client, collab_api):
    response = await client.get(f"/api/v1/ut/collaborations/{P1}")
    assert response.status_code == 200, response.text
    detail = response.json()
    assert (detail["works"], detail["total_works"], detail["share"]) == (3, 6, 0.5)
    assert (detail["status"], detail["openalex_id"]) == ("active", "I1")
    assert detail["labels"] == ["Alpha University", "AU"]
    assert [(link["type"], link["value"]) for link in detail["links"]] == [
        ("wikidata", "Q1"),
        ("homepage", "https://alpha.example"),
    ]
    assert [
        (r["type"], r["ror"], r["label"], r["is_partner"]) for r in detail["relationships"]
    ] == [("related", P2, "Beta Institute", True)]
    assert [(u["name"], u["works"]) for u in detail["ut_faculties"]] == [("ET", 2), ("EWI", 1)]
    assert [(a["pure_uuid"], a["works"]) for a in detail["ut_authors"]] == [("a1", 2), ("a2", 1)]
    assert [(t["value"], t["count"]) for t in detail["works_by_type"]] == [("article", 3)]
    assert [(y["year"], y["works"]) for y in detail["per_year"]] == [
        (2020, 1),
        (2021, 1),
        (2023, 1),
    ]
    assert [(w["pure_uuid"], w["source"], w["corresponding"]) for w in detail["recent_works"]] == [
        ("w4", "openalex", False),
        ("w2", "openalex", False),
        ("w1", "openalex", True),
    ]
    assert detail["recent_works"][0]["authors"] == []
    assert detail["recent_works"][2]["authors"] == ["Test Author"]
    assert [(f["key"], f["works"]) for f in detail["funders"]] == [
        ("openalex:F1", 2),
        ("openalex:F2", 1),
        ("openaire:European Commission", 1),
    ]

    # A filter that leaves the partner no joint work reports zero counts.
    empty = (await client.get(f"/api/v1/ut/collaborations/{P1}", params={"year_from": 2025})).json()
    assert (empty["name"], empty["works"], empty["total_works"], empty["recent_works"]) == (
        "Alpha University",
        0,
        1,
        [],
    )
    assert (await client.get("/api/v1/ut/collaborations/0999zz999")).status_code == 404
    assert (await client.get("/api/v1/ut/collaborations/0999zz999/works")).status_code == 404


@requires_db
async def test_partner_works_and_the_csv_exports(client, collab_api):
    response = await client.get(f"/api/v1/ut/collaborations/{P1}/works")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 3
    assert [(w["pure_uuid"], w["source"], w["corresponding"]) for w in body["items"]] == [
        ("w4", "openalex", False),
        ("w2", "openalex", False),
        ("w1", "openalex", True),
    ]
    assert body["items"][0]["title"] == "Work 4"
    paged = (
        await client.get(f"/api/v1/ut/collaborations/{P1}/works", params={"limit": 1, "offset": 2})
    ).json()
    assert [w["pure_uuid"] for w in paged["items"]] == ["w1"]

    response = await client.get("/api/v1/ut/collaborations/partners.csv")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    lines = response.text.strip().splitlines()
    assert lines[0] == (
        "ror,name,org_type,country_code,city,works,home_corresponding_works,"
        "corresponding_works,authorships,oa_works,closed_works,oa_share,"
        "shares_deals,share,sources,funders,projects"
    )
    assert lines[1] == (
        "01a2b3c04,Alpha University,education,NL,Enschede,3,0,1,4,0,0,0.0,no,0.5,openalex,"
        "Alpha Foundation; Beta Fund; European Commission,A1; PROJ; NWO"
    )
    assert len(lines) == 4

    response = await client.get(f"/api/v1/ut/collaborations/{P1}/works.csv")
    assert response.status_code == 200, response.text
    lines = response.text.strip().splitlines()
    assert lines[0] == (
        "pure_uuid,title,year,doi,work_type,journal,oa_status,deal_covered,"
        "home_corresponding,corresponding,source,authors"
    )
    assert lines[1] == "w4,Work 4,2023,10.0/w4,article,,,no,no,no,openalex,"
    assert lines[-1] == "w1,Work 1,2020,10.0/w1,article,,,no,no,yes,openalex,Test Author"
    assert len(lines) == 4


@requires_db
async def test_trend_counts_each_work_once_per_partner_type(client, collab_api):
    # w1 (2020) reaches an education and a nonprofit partner, so it counts
    # under both types; w5 (2024) has no partner.
    body = (await client.get("/api/v1/ut/collaborations")).json()
    by_year = {y["year"]: y["by_org_type"] for y in body["trend"]}
    assert by_year[2020] == {"education": 1, "nonprofit": 1}
    assert by_year[2021] == {"education": 1}
    assert by_year[2024] == {}

    response = await client.get("/api/v1/ut/collaborations/trend.csv")
    assert response.status_code == 200, response.text
    rows = [line.split(",") for line in response.text.strip().splitlines()]
    header = rows[0]
    assert header[:4] == ["year", "all_works", "collaborative_works", "collaborative_share"]
    table = {row[0]: dict(zip(header, row, strict=True)) for row in rows[1:]}
    assert table["2020"]["education_works"] == "1"
    assert table["2020"]["nonprofit_works"] == "1"
    assert table["2020"]["nonprofit_share"] == "1.0"
    assert table["2020"]["company_works"] == "0"
    assert table["2024"]["collaborative_works"] == "0"
    assert table["2024"]["education_share"] == ""

    narrowed = await client.get("/api/v1/ut/collaborations/trend.csv", params={"type": "nonprofit"})
    table = {line.split(",")[0]: line.split(",") for line in narrowed.text.strip().splitlines()}
    assert table["2021"][header.index("collaborative_works")] == "0"
    assert table["2020"][header.index("education_works")] == "0"


@requires_db
async def test_size_rollup_and_junk_project_filters(client, db, collab_api):
    # Add a mega-collab work (partner_count=25) and a rolled-up child partner,
    # plus a junk 'unidentified' OpenAIRE project and duplicate grant.
    from sqlalchemy import select

    ut = (await db.execute(select(Work.institution_id).limit(1))).scalar_one()
    run_id = (await db.execute(select(Work.first_seen_run).limit(1))).scalar_one()
    db.add(
        Work(
            institution_id=ut,
            pure_uuid="w_mega",
            title="Mega Consortium Paper",
            norm_title="mega consortium paper",
            year=2024,
            doi_normalized="10.0/wmega",
            work_type="info:eu-repo/semantics/article",
            oa_status="hybrid",
            first_seen_run=run_id,
            last_seen_run=run_id,
        )
    )
    db.add(
        PartnerInstitution(
            ror="09child01",
            name="Alpha University Medical Wing",
            org_type="facility",
            country_code="NL",
            city="Enschede",
            parent_ror=P1,
            rollup_ror=P1,
            search_text="alpha university medical wing | enschede | 09child01",
        )
    )
    db.add(
        OpenaireWorkFacts(
            institution_id=ut,
            pure_uuid="w2",
            source_pk="oai:w2",
            projects=[
                {"id": "p_junk", "funder": "DFG", "code": "unidentified"},
                {"id": "p_dup", "funder": "NWO", "code": "B1", "acronym": "BETAPROJ"},
            ],
        )
    )
    await db.flush()
    db.add_all(
        [
            WorkPartner(
                institution_id=ut,
                work_pure_uuid="w_mega",
                partner_ror=P3,
                source="openalex",
                corresponding=False,
                home_corresponding=True,
                authorships=1,
                partner_count=25,
            ),
            WorkPartner(
                institution_id=ut,
                work_pure_uuid="w5",
                partner_ror="09child01",
                source="openalex",
                corresponding=False,
                home_corresponding=True,
                authorships=1,
                partner_count=1,
            ),
        ]
    )
    await db.commit()

    # Standard size (default <=20) excludes w_mega; rollup folds 09child01 into P1.
    std = await search(client)
    by_ror = {i["ror"]: i for i in std["items"]}
    assert "09child01" not in by_ror
    assert by_ror[P1]["works"] == 4  # w1, w2, w4 + rolled-up w5
    assert by_ror[P1]["home_corresponding_works"] == 1
    assert by_ror[P3]["works"] == 1  # w_mega excluded!

    # Raw ROR mode keeps 09child01 separate; size=all brings back w_mega.
    raw = await search(client, rollup="false", size="all")
    by_ror_raw = {i["ror"]: i for i in raw["items"]}
    assert by_ror_raw["09child01"]["works"] == 1
    assert by_ror_raw[P1]["works"] == 3
    assert by_ror_raw[P3]["works"] == 2

    # Junk 'unidentified' project never appears; duplicate grant B1 merges.
    proj_keys = {p["key"]: p for p in std["facets"]["project"]}
    assert "openaire:p_junk" not in proj_keys
    assert proj_keys["openalex:F2/B1"]["acronym"] == "BETAPROJ"
    assert proj_keys["openalex:F2/B1"]["works"] == 2
    assert sorted(proj_keys["openalex:F2/B1"]["sources"]) == ["openaire", "openalex"]
