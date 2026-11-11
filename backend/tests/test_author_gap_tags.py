"""The author page's Pure-match tags on the 'Missing from Pure' list
(explaining rows that are in fact held by Pure), the merged Pure books in
the works list, and the oa_status_source provenance on works items."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import pair_rows, requires_db
from journal_browser.db import get_session
from journal_browser.harvest.pure.xmlrecords import _norm_title
from journal_browser.main import app
from journal_browser.models import (
    Author,
    AuthorWork,
    HarvestRun,
    OpenalexWork,
    Work,
    WorkPureAuthor,
)
from journal_browser.services import authorship

BOOK_DOI = "10.10.0/book"
CHAPTER_DOI = f"{BOOK_DOI}_4"
SAME_TITLE_DOI = "10.10.0/ox"
HELD_DOI = "10.10.0/held"
MISSING_DOI = "10.10.0/miss"
PORTAL = "https://pure.example.com"


def _pure_work(uuid, year, *, title, doi=None, work_type="article", oa="closed"):
    return Work(
        pure_uuid=uuid,
        title=title,
        norm_title=_norm_title(title),
        year=year,
        doi_normalized=doi,
        oa_status=oa,
        work_type=work_type,
    )


def _oa_work(inst_id, w_id, *, title, year, doi, work_type="bookchapter", authorships=()):
    return OpenalexWork(
        institution_id=inst_id,
        w_id=w_id,
        doi_normalized=doi,
        title=title,
        year=year,
        work_type=work_type,
        oa_status="gold",
        venue_issn_l="1234-5678",
        venue_name="Journal One",
        authorships=authorships,
        source="works_stats",
    )


@pytest.fixture
async def gap_db(db, institution_factory):
    """ut with: a Pure book (excluded type, no author_works edge) whose
    chapter lives in the OpenAlex store; a same-title Pure record under a
    different DOI (linked to the author); a DOI held by a Pure record NOT
    linked to the author; and one truly missing store row."""
    ut = await institution_factory(code="ut", research_portal_url=PORTAL)
    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    db.add(run)
    await db.flush()

    def _work(uuid, year, **kw):
        row = _pure_work(uuid, year, **kw)
        row.institution_id = ut.id
        row.first_seen_run = run.id
        row.last_seen_run = run.id
        return row

    db.add_all(
        [
            _work("book1", 2026, title="Eco Anxiety The Book", doi=BOOK_DOI, work_type="book"),
            _work("dup1", 2023, title="Innovation Ethics", doi="10.10.0/other"),
            _work("held", 2023, title="Held Pure Record", doi=HELD_DOI),
            # Regular author works: one DOI-less green record, one with DOI.
            _work("green1", 2022, title="Green No Doi", oa="green"),
            _work("local1", 2024, title="Local Doi", doi="10.10.0/local"),
        ]
    )
    await db.flush()
    db.add_all(
        [
            Author(
                institution_id=ut.id,
                pure_uuid="alice-uuid",
                name="Alice Author",
                openalex_ids=["a-alice"],
                n_works=2,
                confirmed=True,
            ),
            Author(
                institution_id=ut.id,
                pure_uuid="bob-uuid",
                name="Bob Author",
                openalex_ids=["a-bob"],
                n_works=1,
                confirmed=True,
            ),
            # Books keep their Pure author edges even though harvest drops
            # the author_works edge (that is why the merge is needed).
            WorkPureAuthor(institution_id=ut.id, work_pure_uuid="book1", person_uuid="alice-uuid"),
            WorkPureAuthor(institution_id=ut.id, work_pure_uuid="dup1", person_uuid="alice-uuid"),
            # held belongs to bob only: its DOI is in Pure but not Alice's.
            WorkPureAuthor(institution_id=ut.id, work_pure_uuid="held", person_uuid="bob-uuid"),
            AuthorWork(
                institution_id=ut.id, author_pure_uuid="alice-uuid", work_pure_uuid="green1"
            ),
            AuthorWork(
                institution_id=ut.id, author_pure_uuid="alice-uuid", work_pure_uuid="local1"
            ),
        ]
    )
    store = [
        _oa_work(
            ut.id,
            "W-chapter",
            title="Eco Anxiety Chapter Four",
            year=2026,
            doi=CHAPTER_DOI,
            authorships=[{"a": "A-ALICE"}],
        ),
        # Punctuation folds to the same norm title as dup1.
        _oa_work(
            ut.id,
            "W-ox",
            title="Innovation: Ethics!",
            year=2023,
            doi=SAME_TITLE_DOI,
            work_type="article",
            authorships=[{"a": "A-ALICE"}],
        ),
        _oa_work(
            ut.id,
            "W-held",
            title="Held Copy",
            year=2023,
            doi=HELD_DOI,
            work_type="article",
            authorships=[{"a": "A-ALICE"}],
        ),
        _oa_work(
            ut.id,
            "W-miss",
            title="Truly Missing",
            year=2025,
            doi=MISSING_DOI,
            work_type="article",
            authorships=[{"a": "A-ALICE"}],
        ),
    ]
    db.add_all(store)
    db.add_all(pair_rows(*store))
    await db.commit()
    return ut


@pytest.fixture
async def client(db, gap_db):
    async def _override():
        async with async_sessionmaker(db.bind, expire_on_commit=False)() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()


def _portal(uuid):
    return f"{PORTAL}/en/publications/{uuid}"


@requires_db
async def test_profile_pure_match_tags_and_books(client):
    """Each false-positive class gets its tag with the Pure record's
    portal URL, the truly missing row sorts first and is the only likely
    miss, and the Pure book rides in the works list."""
    body = (await client.get("/api/v1/ut/authors/alice-uuid")).json()
    section = body["openalex_only"]
    assert section["total"] == 4
    assert section["likely_missing"] == 1
    rows = [(w["title"], w["pure_match"], w["pure_match_url"]) for w in section["items"]]
    # Untagged first, then year-desc within the tagged group.
    assert rows == [
        ("Truly Missing", None, None),
        ("Eco Anxiety Chapter Four", "parent_book_in_pure", _portal("book1")),
        ("Held Copy", "doi_in_pure", _portal("held")),
        ("Innovation: Ethics!", "same_title_in_pure", _portal("dup1")),
    ]
    assert body["openalex_only_count"] == 4

    works = body["works"]
    assert [w["pure_uuid"] for w in works] == ["book1", "local1", "green1"]
    book = works[0]
    assert book["work_type"] == "book"
    assert book["in_pure"] is True
    # The book stays out of every count: the snapshot n_works (2) and the
    # OA chart both cover the AuthorWork edges only — no 2026 bucket.
    assert body["author"]["n_works"] == 2
    assert all(row["year"] != 2026 for row in body["oa_by_year"])


@requires_db
async def test_profile_oa_status_source(client):
    """DOI-less works carry Pure's own access flag; DOI-matched works are
    OpenAlex-sourced."""
    body = (await client.get("/api/v1/ut/authors/alice-uuid")).json()
    source = {w["pure_uuid"]: w["oa_status_source"] for w in body["works"]}
    assert source["green1"] == "pure"
    assert source["local1"] == "openalex"
    assert body["works"][2]["oa_status"] == "green"


@requires_db
async def test_unit_gap_cards_tagged(db, gap_db):
    """Venue/group gap cards keep the institution-wide DOI anti-join (the
    held-DOI row drops out entirely) and tag parent-book and same-title
    matches, untagged rows first."""
    ut = gap_db
    payload = await authorship.author_ids_openalex_only(db, ut, [["a-alice"]])
    assert payload["total"] == 3
    rows = [(w["title"], w["pure_match"], w["pure_match_url"]) for w in payload["items"]]
    assert rows == [
        ("Truly Missing", None, None),
        ("Eco Anxiety Chapter Four", "parent_book_in_pure", _portal("book1")),
        ("Innovation: Ethics!", "same_title_in_pure", _portal("dup1")),
    ]
