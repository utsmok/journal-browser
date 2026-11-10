"""CSV exports: journal/publisher CRIS-gap lists and author works
(missed/canon). Pins gate parity with the on-screen lists (window, type,
DOI-matches-Pure, author-sweep exclusion for venue lists), the lateral
raw-payload enrichment (latest version wins), roster attribution, and the
publisher context joins."""

import csv
import io
from datetime import UTC, datetime, timedelta

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
    JiscPublisher,
    JournalFlags,
    OpenalexWork,
    SourceRecord,
    Work,
)
from journal_browser.services.exports import CSV_COLUMNS

FACULTY = "Faculty of Science and Technology"
WINDOW_START = 2020


def _oa_work(
    inst_id,
    w_id,
    *,
    title,
    year,
    doi=None,
    work_type="article",
    authorships=(),
    venue="1234-5678",
    source="works_stats",
):
    return OpenalexWork(
        institution_id=inst_id,
        w_id=w_id,
        doi_normalized=doi,
        title=title,
        year=year,
        work_type=work_type,
        oa_status="gold",
        venue_issn_l=venue,
        venue_name="Journal One",
        language="en",
        cited_by_count=7,
        fwci=1.2,
        authorships=authorships,
        author_aids=sorted({a["a"].lower() for a in authorships if a.get("a")}),
        source=source,
    )


@pytest.fixture
async def exports_api(db, institution_factory):
    """ut: the Publisher One group spans journals 1234-5678 + 9999-9999
    with store rows exercising every gate, alice's roster/canon data, and
    two raw works_stats versions for W-gap1 (the later one must win)."""
    ut = await institution_factory(code="ut", data_window_start=WINDOW_START)
    db.add(journal_factory("1234-5678", publisher_name="Publisher One"))
    db.add(journal_factory("9999-9999", publisher_name="Publisher One"))
    db.add(JiscPublisher(id=1, name="Publisher One", ror="https://ror.org/pub01"))
    # above the browsable cutoff so the publisher group resolves
    db.add_all(
        [
            JournalFlags(
                institution_id=ut.id, issn_l="1234-5678", works_count=1, works_window_plus=5
            ),
            JournalFlags(
                institution_id=ut.id, issn_l="9999-9999", works_count=1, works_window_plus=5
            ),
        ]
    )
    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    raw_run = HarvestRun(
        source="openalex", entity_type="works_stats", status="completed", config_fingerprint="t"
    )
    db.add_all([run, raw_run])
    await db.flush()

    def _work(uuid, year, issn="1234-5678", doi=None):
        return Work(
            institution_id=ut.id,
            pure_uuid=uuid,
            title=f"Work {uuid}",
            norm_title=f"work {uuid}",
            year=year,
            doi_normalized=doi,
            journal_issn_l=issn,
            first_seen_run=run.id,
            last_seen_run=run.id,
        )

    db.add(_work("w1", 2023, doi="10.0.0/w1"))
    await db.flush()  # the work FK must exist before the author edge
    db.add_all(
        [
            Author(
                institution_id=ut.id,
                pure_uuid="alice-uuid",
                name="Alice Author",
                orcid="0000-0002-1111",
                faculty=FACULTY,
                research_group="Group X",
                institute="DSI",
                openalex_ids=["a-alice"],
                n_works=1,
                confirmed=True,
            ),
            AuthorWork(institution_id=ut.id, author_pure_uuid="alice-uuid", work_pure_uuid="w1"),
        ]
    )
    db.add_all(
        [
            _oa_work(
                ut.id,
                "W-gap1",
                doi="10.9.0/1",
                title="Gap One",
                year=2024,
                authorships=[{"a": "A-ALICE", "n": "Alice Author", "o": "0000-0002-1111"}],
            ),
            _oa_work(
                ut.id,
                "W-gap2",
                title="Gap Two Untyped",
                year=2023,
                venue="9999-9999",
                work_type=None,
            ),
            # venue-gated: harvested from an author profile
            _oa_work(
                ut.id,
                "W-sweep",
                doi="10.9.0/6",
                title="Sweep Only",
                year=2024,
                source="author-sweep",
            ),
            # DOI matches a pure work -> anti-join drops it everywhere
            _oa_work(ut.id, "W-matched", doi="10.0.0/w1", title="Matched", year=2023),
            _oa_work(
                ut.id, "W-pre", doi="10.9.0/9", title="Preprint", year=2024, work_type="preprint"
            ),
            _oa_work(ut.id, "W-old", doi="10.9.0/8", title="Old", year=2019),
            # author-attributed row in a venue outside the group
            _oa_work(
                ut.id,
                "W-ghost",
                doi="10.9.0/7",
                title="Ghost",
                year=2024,
                venue="7777-7777",
                authorships=[{"a": "A-ALICE", "n": "Alice Author", "o": None}],
            ),
        ]
    )
    now = datetime.now(UTC)
    db.add_all(
        [
            SourceRecord(
                source="openalex",
                entity_type="works_stats",
                source_pk="W-gap1",
                payload={"publication_date": "1999-09-09"},
                content_hash="old",
                harvested_at=now - timedelta(hours=2),
                harvest_run_id=raw_run.id,
            ),
            SourceRecord(
                source="openalex",
                entity_type="works_stats",
                source_pk="W-gap1",
                payload={
                    "publication_date": "2024-05-01",
                    "best_oa_location": {
                        "pdf_url": "https://oa.example/gap1.pdf",
                        "landing_page_url": "https://best.example/gap1",
                    },
                    "primary_location": {
                        "pdf_url": None,
                        "landing_page_url": "https://primary.example/gap1",
                    },
                    "authorships": [
                        {
                            "institutions": [
                                {"ror": "https://ror.org/02"},
                                {"ror": None},
                                {"ror": "https://ror.org/02"},
                            ]
                        }
                    ],
                },
                content_hash="new",
                harvested_at=now - timedelta(hours=1),
                harvest_run_id=raw_run.id,
            ),
        ]
    )
    await db.commit()

    async def _override():
        async with async_sessionmaker(db.bind, expire_on_commit=False)() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client
    app.dependency_overrides.clear()


def _rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


@requires_db
async def test_journal_gap_csv_enriched(exports_api):
    r = await exports_api.get("/api/v1/ut/journals/1234-5678/openalex-only.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"] == 'attachment; filename="1234-5678-openalex-only.csv"'
    rows = _rows(r.text)
    assert list(rows[0]) == list(CSV_COLUMNS)
    # gates mirror the on-screen card: author-sweep, matched-DOI,
    # excluded-type, and out-of-window rows stay out
    assert [row["title"] for row in rows] == ["Gap One"]
    gap1 = rows[0]
    assert gap1["openalex_id"] == "W-gap1"
    assert gap1["openalex_url"] == "https://openalex.org/W-gap1"
    assert gap1["publication_year"] == "2024"
    # raw enrichment: the LATEST source_record version wins, pdf from
    # best_oa_location, landing from primary_location, rors distinct
    assert gap1["publication_date"] == "2024-05-01"
    assert gap1["pdf_url"] == "https://oa.example/gap1.pdf"
    assert gap1["landing_page_url"] == "https://primary.example/gap1"
    assert gap1["institution_rors"] == "https://ror.org/02"
    assert gap1["doi"] == "10.9.0/1"
    assert gap1["doi_url"] == "https://doi.org/10.9.0/1"
    # authorships + roster attribution
    assert gap1["authors"] == "Alice Author"
    assert gap1["authors_openalex_ids"] == "A-ALICE"
    assert gap1["authors_orcids"] == "0000-0002-1111"
    assert gap1["ut_authors"] == "Alice Author"
    assert gap1["ut_authors_orcids"] == "0000-0002-1111"
    assert gap1["ut_affiliations"] == f"{FACULTY} / Group X / DSI"
    # venue + publisher context
    assert gap1["journal_title"] == "Journal One"
    assert gap1["issn_l"] == "1234-5678"
    assert gap1["publisher_name"] == "Publisher One"
    assert gap1["publisher_ror"] == "https://ror.org/pub01"
    assert gap1["oa_status"] == "gold"
    assert gap1["work_type"] == "article"
    assert gap1["language"] == "en"
    assert gap1["cited_by_count"] == "7"
    assert gap1["fwci"] == "1.2"
    assert gap1["is_retracted"] == "False"
    assert gap1["in_pure"] == "false"


@requires_db
async def test_journal_gap_csv_unknown_journal(exports_api):
    r = await exports_api.get("/api/v1/ut/journals/0000-0000/openalex-only.csv")
    assert r.status_code == 404


@requires_db
async def test_publisher_gap_csv_spans_group(exports_api):
    r = await exports_api.get("/api/v1/ut/publishers/Publisher One/openalex-only.csv")
    assert r.status_code == 200
    assert (
        r.headers["content-disposition"] == 'attachment; filename="Publisher-One-openalex-only.csv"'
    )
    rows = _rows(r.text)
    # both group journals contribute; gated rows stay out
    assert [row["title"] for row in rows] == ["Gap One", "Gap Two Untyped"]
    gap2 = rows[1]
    assert gap2["issn_l"] == "9999-9999"
    # no raw payload stored for W-gap2: raw-derived cells stay empty
    assert gap2["publication_date"] == ""
    assert gap2["pdf_url"] == ""
    assert gap2["institution_rors"] == ""
    assert gap2["doi"] == ""
    # NULL work type survives the gate and lands empty
    assert gap2["work_type"] == ""
    assert gap2["ut_authors"] == ""
    assert gap2["publisher_name"] == "Publisher One"


@requires_db
async def test_publisher_gap_csv_unknown(exports_api):
    r = await exports_api.get("/api/v1/ut/publishers/No Such Publisher/openalex-only.csv")
    assert r.status_code == 404


@requires_db
async def test_author_works_csv_missed(exports_api):
    r = await exports_api.get("/api/v1/ut/authors/alice-uuid/works.csv", params={"scope": "missed"})
    assert r.status_code == 200
    assert r.headers["content-disposition"] == 'attachment; filename="alice-uuid-works-missed.csv"'
    rows = _rows(r.text)
    # attribution is author-scoped, not venue-scoped: the group-external
    # ghost row counts; matched-DOI/sweep rows have no attribution
    assert [row["title"] for row in rows] == ["Gap One", "Ghost"]
    ghost = rows[1]
    assert ghost["openalex_id"] == "W-ghost"
    assert ghost["ut_authors"] == "Alice Author"
    assert ghost["ut_authors_orcids"] == "0000-0002-1111"
    # no journal row for 7777-7777: publisher context degrades to empty
    assert ghost["publisher_name"] == ""
    assert ghost["publisher_ror"] == ""
    assert ghost["in_pure"] == "false"
    # W-gap2/W-sweep carry no alice authorship -> absent
    assert {row["openalex_id"] for row in rows} == {"W-gap1", "W-ghost"}


@requires_db
async def test_author_works_csv_canon(exports_api):
    r = await exports_api.get("/api/v1/ut/authors/alice-uuid/works.csv", params={"scope": "canon"})
    assert r.status_code == 200
    assert r.headers["content-disposition"] == 'attachment; filename="alice-uuid-works-canon.csv"'
    rows = _rows(r.text)
    assert [row["title"] for row in rows] == ["Work w1"]
    work = rows[0]
    # OpenAlex-side columns stay empty except the DOI
    assert work["openalex_id"] == ""
    assert work["openalex_url"] == ""
    assert work["publication_date"] == ""
    assert work["doi"] == "10.0.0/w1"
    assert work["doi_url"] == "https://doi.org/10.0.0/w1"
    assert work["publication_year"] == "2023"
    assert work["journal_title"] == "Journal 1234-5678"
    assert work["issn_l"] == "1234-5678"
    assert work["publisher_name"] == "Publisher One"
    assert work["publisher_ror"] == "https://ror.org/pub01"
    # the page author is the sole UT author
    assert work["ut_authors"] == "Alice Author"
    assert work["ut_authors_orcids"] == "0000-0002-1111"
    assert work["ut_affiliations"] == f"{FACULTY} / Group X / DSI"
    assert work["in_pure"] == "true"


@requires_db
async def test_author_works_csv_bad_scope(exports_api):
    r = await exports_api.get(
        "/api/v1/ut/authors/alice-uuid/works.csv", params={"scope": "everything"}
    )
    assert r.status_code == 400


@requires_db
async def test_author_works_csv_unknown_author(exports_api):
    r = await exports_api.get("/api/v1/ut/authors/nope/works.csv")
    assert r.status_code == 404
