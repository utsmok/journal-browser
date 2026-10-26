"""Author browsing API: scoped search, profile bundle shape, recommendation
sections honoring journal visibility, and enabled=false degradation."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import requires_db
from journal_browser.db import get_session
from journal_browser.main import app
from journal_browser.models import (
    Author,
    AuthorWork,
    HarvestRun,
    Journal,
    JournalFlags,
    Work,
)

DIM = 384


def _vec(i: int) -> list[float]:
    return [1.0 if j == i else 0.0 for j in range(DIM)]


def _journal(issn_l: str, **kw) -> Journal:
    base = dict(
        issn_l=issn_l,
        title=f"Journal {issn_l}",
        type="journal",
        is_oa=False,
        is_in_doaj=False,
        in_scimago=False,
        works_2020_plus=10,
        search_text=f"Journal {issn_l}",
    )
    base.update(kw)
    return Journal(**base)


@pytest.fixture
async def authors_api(db, institution_factory):
    """ut: one author (Alice, 4 works) in J1 (covered hybrid) + J2
    (subscription); candidates J3 (diamond), J4 (covered), J5 (below
    cutoff), J6 (browse-excluded); rug: no author data at all."""

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
            _journal("1234-5678", embedding=_vec(0)),  # J1: hybrid (covered)
            _journal("2222-2221", embedding=_vec(1)),  # J2: subscription
            _journal("3333-3331", is_in_doaj=True, embedding=_vec(2)),  # J3: diamond
            _journal("4444-4441", embedding=_vec(3)),  # J4: covered hybrid
            _journal("5555-5551", embedding=_vec(4)),  # below cutoff
            _journal("6666-6661", embedding=_vec(5)),  # browse-excluded
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
    alice = Author(
        institution_id=ut.id,
        pure_uuid="alice-uuid",
        name="Alice Author",
        orcid="0000-0002-1111",
        openalex_author_id="a5038098443",
        faculty="Faculty of Science and Technology",
        research_group="Quantum Transport in Matter",
        orgs=["Quantum Transport in Matter", "University of Twente"],
        n_works=4,
    )
    session.add(alice)
    await session.flush()
    def _edge(work: str) -> AuthorWork:
        return AuthorWork(
            institution_id=ut.id, author_pure_uuid="alice-uuid", work_pure_uuid=work
        )

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
    assert body["total"] == 1
    assert [item["pure_uuid"] for item in body["items"]] == ["alice-uuid"]
    item = body["items"][0]
    assert item == {
        "pure_uuid": "alice-uuid",
        "name": "Alice Author",
        "faculty": "Faculty of Science and Technology",
        "research_group": "Quantum Transport in Matter",
        "n_works": 4,
        "orcid": "0000-0002-1111",
    }
    hit = await authors_api.get("/api/v1/ut/authors", params={"q": "alice"})
    assert hit.json()["total"] == 1 and len(hit.json()["items"]) == 1
    miss = await authors_api.get("/api/v1/ut/authors", params={"q": "nobody"})
    assert miss.json()["total"] == 0 and miss.json()["items"] == []


@requires_db
async def test_search_not_enabled_and_unknown_institution(authors_api):
    body = (await authors_api.get("/api/v1/rug/authors")).json()
    assert body == {"enabled": False, "total": 0, "items": []}
    assert (await authors_api.get("/api/v1/nonsense/authors")).status_code == 404


@requires_db
async def test_profile_shape(authors_api):
    r = await authors_api.get("/api/v1/ut/authors/alice-uuid")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {
        "author", "oa_by_year", "journals", "topics", "similar", "alternatives", "works",
    }
    author = body["author"]
    assert author["orgs"] == ["Quantum Transport in Matter", "University of Twente"]
    assert author["n_works"] == 4
    # year desc, known buckets only (diamond counts in total, no column)
    assert [row["year"] for row in body["oa_by_year"]] == [2024, 2023, 2021]
    assert body["oa_by_year"][1] == {
        "year": 2023, "total": 2, "gold": 1, "green": 0, "hybrid": 0, "bronze": 0, "closed": 1,
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


@requires_db
async def test_profile_unknown_author(authors_api):
    assert (await authors_api.get("/api/v1/ut/authors/nope")).status_code == 404
