"""Author browsing API: scoped search, profile bundle shape, recommendation
sections honoring journal visibility, and enabled=false degradation."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import journal_factory, requires_db
from journal_browser.db import get_session
from journal_browser.main import app
from journal_browser.models import (
    Author,
    AuthorWork,
    HarvestRun,
    JournalFlags,
    Work,
)

DIM = 384


def _vec(i: int) -> list[float]:
    return [1.0 if j == i else 0.0 for j in range(DIM)]


@pytest.fixture
async def authors_api(db, institution_factory):
    """ut: four authors — Alice (confirmed, 4 works) in J1 (covered hybrid)
    + J2 (subscription), Carol (confirmed, 1 work), Dan (confirmed, 50
    works), Bob (unconfirmed, 50 works); candidates J3 (diamond), J4
    (covered), J5 (below cutoff), J6 (browse-excluded); rug: no author
    data at all."""

    async def _override():
        async with async_sessionmaker(db.bind, expire_on_commit=False)() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    ut = await institution_factory(code="ut")
    await institution_factory(code="rug")

    session = db
    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    session.add(run)
    await session.flush()
    session.add_all(
        [
            journal_factory("1234-5678", embedding=_vec(0)),  # J1: hybrid (covered)
            journal_factory("2222-2221", embedding=_vec(1)),  # J2: subscription
            journal_factory(
                "3333-3331",
                is_in_doaj=True,
                doaj_in_doaj=True,
                doaj_has_apc=False,
                embedding=_vec(2),
            ),  # J3: diamond
            journal_factory("4444-4441", embedding=_vec(3)),  # J4: covered hybrid
            journal_factory("5555-5551", embedding=_vec(4)),  # below cutoff
            journal_factory("6666-6661", embedding=_vec(5)),  # browse-excluded
        ]
    )
    await session.flush()

    def _flags(issn_l: str, **kw) -> JournalFlags:
        return JournalFlags(institution_id=ut.id, issn_l=issn_l, **kw)

    session.add_all(
        [
            _flags("1234-5678", works_count=3, works_window_plus=10, deal_covered=True),
            _flags("2222-2221", works_count=1, works_window_plus=5),
            _flags("3333-3331", works_count=0, works_window_plus=10),
            _flags("4444-4441", works_count=0, works_window_plus=10, deal_covered=True),
            _flags("5555-5551", works_count=0, works_window_plus=1),
            _flags("6666-6661", works_count=0, works_window_plus=10, browse_excluded=True),
        ]
    )

    def _work(uuid: str, year: int, issn: str, oa: str) -> Work:
        return Work(
            institution_id=ut.id,
            pure_uuid=uuid,
            title=f"Work {uuid}",
            norm_title=f"work {uuid}",
            year=year,
            oa_status=oa,
            journal_issn_l=issn,
            first_seen_run=run.id,
            last_seen_run=run.id,
        )

    session.add_all(
        [
            _work("w-2024", 2024, "1234-5678", "hybrid"),
            _work("w-2023a", 2023, "1234-5678", "gold"),
            _work("w-2023b", 2023, "2222-2221", "closed"),
            _work("w-2021", 2021, "1234-5678", "diamond"),
        ]
    )
    TNW = "Faculty of Science and Technology"
    BMS = "Faculty of Behavioural, Management and Social Sciences"
    session.add_all(
        [
            # Confirmed: shows in search by default.
            Author(
                institution_id=ut.id,
                pure_uuid="alice-uuid",
                name="Alice Author",
                orcid="0000-0002-1111",
                openalex_author_id="a5038098443",
                faculty=TNW,
                research_group="Quantum Transport in Matter",
                orgs=["Quantum Transport in Matter", "University of Twente"],
                n_works=4,
                confirmed=True,
                last_pub_year=2024,
                primary_topic="Physics",
            ),
            # Confirmed, no orcid, never published in-window.
            Author(
                institution_id=ut.id,
                pure_uuid="carol-uuid",
                name="Carol Navigator",
                faculty=TNW,
                research_group="Quantum Navigation",
                orgs=["Quantum Navigation"],
                n_works=1,
                confirmed=True,
                last_pub_year=None,
                primary_topic="Physics",
            ),
            # Confirmed, heavy producer in the 2020-2021 bucket.
            Author(
                institution_id=ut.id,
                pure_uuid="dan-uuid",
                name="Dan Datagov",
                orcid="0000-0002-3333",
                faculty=BMS,
                research_group="Governance of Data",
                orgs=["Governance of Data"],
                n_works=50,
                confirmed=True,
                last_pub_year=2021,
                primary_topic="Chemistry",
            ),
            # Unconfirmed: hidden from search while the flag is on.
            Author(
                institution_id=ut.id,
                pure_uuid="bob-uuid",
                name="Bob Noaffiliation",
                faculty=TNW,
                research_group="Quantum Navigation",
                orgs=["Quantum Navigation"],
                n_works=50,
                confirmed=False,
                last_pub_year=2025,
                primary_topic="Chemistry",
            ),
        ]
    )
    await session.flush()

    def _edge(work: str) -> AuthorWork:
        return AuthorWork(institution_id=ut.id, author_pure_uuid="alice-uuid", work_pure_uuid=work)

    session.add_all([_edge("w-2024"), _edge("w-2023a"), _edge("w-2023b"), _edge("w-2021")])
    await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client
    app.dependency_overrides.clear()


@requires_db
async def test_search_ranked_and_filtered(authors_api):
    r = await authors_api.get("/api/v1/ut/authors")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    # Bob is unconfirmed and hidden while require_confirmed_affiliation is on.
    assert body["total"] == 3
    assert [item["pure_uuid"] for item in body["items"]] == ["dan-uuid", "alice-uuid", "carol-uuid"]
    item = body["items"][1]
    assert item == {
        "pure_uuid": "alice-uuid",
        "name": "Alice Author",
        "faculty": "Faculty of Science and Technology",
        "research_group": "Quantum Transport in Matter",
        "n_works": 4,
        "orcid": "0000-0002-1111",
        "confirmed": True,
        "last_pub_year": 2024,
        "primary_topic": "Physics",
    }
    hit = await authors_api.get("/api/v1/ut/authors", params={"q": "alice"})
    assert hit.json()["total"] == 1 and len(hit.json()["items"]) == 1
    miss = await authors_api.get("/api/v1/ut/authors", params={"q": "nobody"})
    assert miss.json()["total"] == 0 and miss.json()["items"] == []


@requires_db
async def test_search_not_enabled_and_unknown_institution(authors_api):
    body = (await authors_api.get("/api/v1/rug/authors")).json()
    assert body == {
        "enabled": False,
        "total": 0,
        "offset": 0,
        "sort": "works_desc",
        "items": [],
        "facets": {},
    }
    assert (await authors_api.get("/api/v1/nonsense/authors")).status_code == 404


@requires_db
async def test_profile_shape(authors_api):
    r = await authors_api.get("/api/v1/ut/authors/alice-uuid")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {
        "author",
        "oa_by_year",
        "journals",
        "topics",
        "similar",
        "alternatives",
        "works",
    }
    author = body["author"]
    assert author["orgs"] == ["Quantum Transport in Matter", "University of Twente"]
    assert author["n_works"] == 4
    # year desc, known buckets only (diamond counts in total, no column)
    assert [row["year"] for row in body["oa_by_year"]] == [2024, 2023, 2021]
    assert body["oa_by_year"][1] == {
        "year": 2023,
        "total": 2,
        "gold": 1,
        "green": 0,
        "hybrid": 0,
        "bronze": 0,
        "closed": 1,
        "diamond": 0,
    }
    # journals: works count desc, shared oa_type case
    assert [(j["issn_l"], j["n_works"], j["oa_type"]) for j in body["journals"]] == [
        ("1234-5678", 3, "hybrid"),
        ("2222-2221", 1, "subscription"),
    ]


@requires_db
async def test_profile_similar_visibility(authors_api):
    body = (await authors_api.get("/api/v1/ut/authors/alice-uuid")).json()
    similar = body["similar"]
    # Author venues (1234-5678, 2222-2221), below-cutoff 5555 and
    # browse-excluded 6666 never appear; orthogonal unit vectors make the
    # two visible candidates tie at distance 1 -> issn order.
    assert [j["issn_l"] for j in similar["all"]] == ["3333-3331", "4444-4441"]
    assert all(j["score"] == 0.0 for j in similar["all"])  # orthogonal -> distance 1
    assert [j["issn_l"] for j in similar["deals"]] == ["4444-4441"]
    assert [j["issn_l"] for j in similar["diamond"]] == ["3333-3331"]
    diamond = similar["diamond"][0]
    assert diamond["oa_type"] == "diamond" and diamond["deal_covered"] is False


@requires_db
async def test_profile_alternatives(authors_api):
    body = (await authors_api.get("/api/v1/ut/authors/alice-uuid")).json()
    alts = body["alternatives"]
    # Both author venues are non-OA; options are the diamond/covered
    # candidates only, author venues excluded.
    assert [(a["issn_l"], a["n_works"]) for a in alts] == [
        ("1234-5678", 3),
        ("2222-2221", 1),
    ]
    for alt in alts:
        assert {o["issn_l"] for o in alt["options"]} == {"3333-3331", "4444-4441"}
        assert all(o["oa_type"] in ("diamond", "hybrid") for o in alt["options"])


@requires_db
async def test_profile_works_sorted_and_joined(authors_api):
    body = (await authors_api.get("/api/v1/ut/authors/alice-uuid")).json()
    works = body["works"]
    assert [w["pure_uuid"] for w in works] == ["w-2024", "w-2023a", "w-2023b", "w-2021"]
    assert works[0]["journal_title"] == "Journal 1234-5678"
    assert works[0]["doi"] is None
    assert works[2]["journal_title"] == "Journal 2222-2221"
    assert all(w["in_pure"] for w in works)


@requires_db
async def test_profile_openalex_only_merge(authors_api, db, monkeypatch):
    """OpenAlex-attributed works absent from Pure append after the local
    ones with in_pure False; window, excluded-type, and DOI-duplicate gates
    drop the rest."""
    from sqlalchemy import update

    await db.execute(
        update(Author).where(Author.pure_uuid == "alice-uuid").values(openalex_ids=["a5038098443"])
    )
    await db.execute(
        update(Work).where(Work.pure_uuid == "w-2024").values(doi_normalized="10.1000/local")
    )
    await db.commit()

    async def _fake(_aids, dsn=None):
        return [
            # Duplicate of the local w-2024 by DOI: dropped (prefix noise on
            # purpose — normalize_doi must fold it).
            {
                "title": "Dup",
                "year": 2024,
                "doi": "https://doi.org/10.1000/LOCAL",
                "oa_status": "gold",
                "work_type": "article",
                "venue_name": None,
                "issn_l": None,
            },
            # Outside the institution's data window: dropped.
            {
                "title": "Old",
                "year": 1999,
                "doi": "10.1000/old",
                "oa_status": "closed",
                "work_type": "article",
                "venue_name": None,
                "issn_l": None,
            },
            # Excluded work type: dropped.
            {
                "title": "Pre",
                "year": 2021,
                "doi": None,
                "oa_status": None,
                "work_type": "preprint",
                "venue_name": None,
                "issn_l": None,
            },
            # Kept: new DOI, in window.
            {
                "title": "Only OA",
                "year": 2022,
                "doi": "10.1000/oa-only",
                "oa_status": None,
                "work_type": None,
                "venue_name": "Outside Journal",
                "issn_l": "9999-9991",
            },
            # Kept: no DOI to dedupe on.
            {
                "title": "No Doi",
                "year": 2020,
                "doi": None,
                "oa_status": "green",
                "work_type": "article",
                "venue_name": None,
                "issn_l": None,
            },
        ]

    monkeypatch.setattr("journal_browser.services.authors.ut_openalex_only_works_for_author", _fake)
    body = (await authors_api.get("/api/v1/ut/authors/alice-uuid")).json()
    works = body["works"]
    assert [w["pure_uuid"] for w in works if w["in_pure"]] == [
        "w-2024",
        "w-2023a",
        "w-2023b",
        "w-2021",
    ]
    merged = [w for w in works if not w["in_pure"]]
    assert [(w["title"], w["doi"]) for w in merged] == [
        ("Only OA", "10.1000/oa-only"),
        ("No Doi", None),
    ]
    assert merged[0]["oa_status"] == "unknown"
    assert merged[0]["journal_title"] == "Outside Journal"
    assert merged[0]["journal_issn_l"] == "9999-9991"


@requires_db
async def test_profile_unknown_author(authors_api):
    assert (await authors_api.get("/api/v1/ut/authors/nope")).status_code == 404


@requires_db
async def test_require_confirmed_affiliation_toggle(authors_api, db):
    from sqlalchemy import update

    from journal_browser.models import Institution

    # Default on: Bob (unconfirmed) is hidden from search but his profile
    # endpoint stays reachable.
    body = (await authors_api.get("/api/v1/ut/authors", params={"q": "bob"})).json()
    assert body["total"] == 0 and body["items"] == []
    assert (await authors_api.get("/api/v1/ut/authors/bob-uuid")).status_code == 200

    await db.execute(
        update(Institution)
        .where(Institution.code == "ut")
        .values(require_confirmed_affiliation=False)
    )
    await db.commit()

    body = (await authors_api.get("/api/v1/ut/authors")).json()
    assert body["total"] == 4
    assert [i["pure_uuid"] for i in body["items"]] == [
        "bob-uuid",
        "dan-uuid",
        "alice-uuid",
        "carol-uuid",
    ]
    bob = next(i for i in body["items"] if i["pure_uuid"] == "bob-uuid")
    assert bob["confirmed"] is False
    # Facet counts respect the flag: Bob joins the 50+ / 2025-2026 buckets.
    assert {f["value"]: f["count"] for f in body["facets"]["works"]} == {"1-4": 2, "50+": 2}
    assert {f["value"]: f["count"] for f in body["facets"]["last_pub"]} == {
        "2020-2021": 1,
        "2022-2024": 1,
        "2025-2026": 1,
        "none": 1,
    }


@requires_db
async def test_search_folds_diacritics(authors_api, db):
    from sqlalchemy import select

    from journal_browser.models import Author, Institution

    ut_id = await db.scalar(select(Institution.id).where(Institution.code == "ut"))
    db.add(
        Author(
            institution_id=ut_id,
            pure_uuid="julia-uuid",
            name="Jülia Föllmer",
            orgs=[],
            n_works=0,
            confirmed=True,
        )
    )
    await db.commit()
    # Plain-ASCII query finds the umlauted name; the accented query still works.
    for q in ("follmer", "Föllmer", "julia"):
        body = (await authors_api.get("/api/v1/ut/authors", params={"q": q})).json()
        assert [i["pure_uuid"] for i in body["items"]] == ["julia-uuid"], q


@requires_db
async def test_facets_and_filters(authors_api):
    body = (await authors_api.get("/api/v1/ut/authors")).json()
    facets = body["facets"]
    # has_orcid is boolean: no facet list.
    assert set(facets) == {"faculty", "org", "works", "last_pub", "topic"}
    assert facets["faculty"] == [
        {"value": "Faculty of Science and Technology", "count": 2},
        {"value": "Faculty of Behavioural, Management and Social Sciences", "count": 1},
    ]
    assert facets["org"] == [
        {"value": "Governance of Data", "count": 1},
        {"value": "Quantum Navigation", "count": 1},
        {"value": "Quantum Transport in Matter", "count": 1},
    ]
    # Strata edges: n_works 1 and 4 -> "1-4", 50 -> "50+".
    assert facets["works"] == [{"value": "1-4", "count": 2}, {"value": "50+", "count": 1}]
    assert facets["last_pub"] == [
        {"value": "2020-2021", "count": 1},
        {"value": "2022-2024", "count": 1},
        {"value": "none", "count": 1},
    ]
    assert facets["topic"] == [{"value": "Physics", "count": 2}, {"value": "Chemistry", "count": 1}]

    # Own dimension stays unfiltered in its facet; the others apply.
    tnw = "Faculty of Science and Technology"
    body = (await authors_api.get("/api/v1/ut/authors", params={"faculty": tnw})).json()
    assert body["total"] == 2
    assert [i["pure_uuid"] for i in body["items"]] == ["alice-uuid", "carol-uuid"]
    assert len(body["facets"]["faculty"]) == 2
    assert body["facets"]["topic"] == [{"value": "Physics", "count": 2}]

    # Pipe multi-select ORs within a dimension ("|", not ",": facet values contain commas).
    body = (
        await authors_api.get("/api/v1/ut/authors", params={"last_pub": "none|2020-2021"})
    ).json()
    assert [i["pure_uuid"] for i in body["items"]] == ["dan-uuid", "carol-uuid"]

    # A facet value containing a comma survives (regression: comma was the separator).
    bms = "Faculty of Behavioural, Management and Social Sciences"
    body = (await authors_api.get("/api/v1/ut/authors", params={"faculty": bms})).json()
    assert body["total"] == 1

    # Dimensions AND together.
    body = (
        await authors_api.get(
            "/api/v1/ut/authors", params={"faculty": tnw, "org": "Quantum Navigation"}
        )
    ).json()
    assert [i["pure_uuid"] for i in body["items"]] == ["carol-uuid"]

    body = (await authors_api.get("/api/v1/ut/authors", params={"works": "50+"})).json()
    assert [i["pure_uuid"] for i in body["items"]] == ["dan-uuid"]

    body = (await authors_api.get("/api/v1/ut/authors", params={"has_orcid": "no"})).json()
    assert [i["pure_uuid"] for i in body["items"]] == ["carol-uuid"]
    body = (await authors_api.get("/api/v1/ut/authors", params={"has_orcid": "yes"})).json()
    assert [i["pure_uuid"] for i in body["items"]] == ["dan-uuid", "alice-uuid"]

    body = (await authors_api.get("/api/v1/ut/authors", params={"topic": "Physics"})).json()
    assert body["total"] == 2

    # Unknown filter values: empty result set, no error.
    r = await authors_api.get("/api/v1/ut/authors", params={"works": "7-9"})
    assert r.status_code == 200
    assert r.json()["total"] == 0 and r.json()["items"] == []
    # Every facet but its own dimension collapses; works keeps its buckets.
    facets = r.json()["facets"]
    assert facets["works"] == [{"value": "1-4", "count": 2}, {"value": "50+", "count": 1}]
    assert all(v == [] for k, v in facets.items() if k != "works")
    r = await authors_api.get("/api/v1/ut/authors", params={"has_orcid": "maybe"})
    assert r.status_code == 422
    r = await authors_api.get("/api/v1/ut/authors", params={"last_pub": "stone-age"})
    assert r.status_code == 200 and r.json()["total"] == 0


@requires_db
async def test_sort_keys_and_offset_paging(authors_api):
    # Default works_desc: 50, 4, 1.
    r = await authors_api.get("/api/v1/ut/authors")
    assert [i["pure_uuid"] for i in r.json()["items"]] == ["dan-uuid", "alice-uuid", "carol-uuid"]
    assert r.json()["sort"] == "works_desc" and r.json()["offset"] == 0

    body = (await authors_api.get("/api/v1/ut/authors", params={"sort": "name_asc"})).json()
    assert [i["pure_uuid"] for i in body["items"]] == ["alice-uuid", "carol-uuid", "dan-uuid"]
    body = (await authors_api.get("/api/v1/ut/authors", params={"sort": "name_desc"})).json()
    assert [i["pure_uuid"] for i in body["items"]] == ["dan-uuid", "carol-uuid", "alice-uuid"]

    # Nulls last: 2024, 2021, then carol's null.
    body = (await authors_api.get("/api/v1/ut/authors", params={"sort": "last_pub_desc"})).json()
    assert [i["pure_uuid"] for i in body["items"]] == ["alice-uuid", "dan-uuid", "carol-uuid"]
    assert body["sort"] == "last_pub_desc"

    # Sort applies after filters; q keeps its prefix-rank only on the
    # default sort.
    body = (
        await authors_api.get(
            "/api/v1/ut/authors",
            params={"sort": "last_pub_desc", "faculty": "Faculty of Science and Technology"},
        )
    ).json()
    assert [i["pure_uuid"] for i in body["items"]] == ["alice-uuid", "carol-uuid"]

    # Offset pages within the same filtered set; total stays unpaginated.
    body = (await authors_api.get("/api/v1/ut/authors", params={"offset": 1, "limit": 2})).json()
    assert [i["pure_uuid"] for i in body["items"]] == ["alice-uuid", "carol-uuid"]
    assert body["total"] == 3 and body["offset"] == 1
    body = (await authors_api.get("/api/v1/ut/authors", params={"offset": 9})).json()
    assert body["items"] == [] and body["total"] == 3

    # Facets ignore offset (they describe the filtered set).
    body = (await authors_api.get("/api/v1/ut/authors", params={"offset": 1})).json()
    assert body["facets"]["works"] == [{"value": "1-4", "count": 2}, {"value": "50+", "count": 1}]

    # Unknown sort key: 422 (Literal validation); negative offset too.
    assert (await authors_api.get("/api/v1/ut/authors", params={"sort": "nope"})).status_code == 422
    assert (await authors_api.get("/api/v1/ut/authors", params={"offset": -1})).status_code == 422
