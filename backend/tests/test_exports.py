"""CSV exports as served: the journal/publisher CRIS-gap downloads mirror
the on-screen cards' gates (author-sweep rows, DOI-matched-Pure rows,
excluded types and out-of-window years stay out), the lateral raw-payload
enrichment picks the latest source_record version per work, roster and
publisher context batch-join, the formula guard prefixes spreadsheet-active
leading characters, and the year lens narrows the rows. Author works
splits missed (store rows attributed to the author) from canon (Pure
works), with the same 404/400 boundaries.
"""

import csv
import io

import pytest

from conftest import journal_factory, pair_rows, requires_db
from journal_browser.models import (
    Author,
    AuthorWork,
    HarvestRun,
    JiscPublisher,
    JournalFlags,
    OpenalexWork,
    Work,
)
from journal_browser.services.exports import CSV_COLUMNS

FACULTY = "Faculty of Science and Technology"
PUB = "Publisher One"

#: (w_id, title, year, venue, doi, work_type, source, authorships).
STORE_WORKS = [
    (
        "W-GAP1",
        'Gap, "One"',
        2024,
        "1234-5678",
        "10.9.0/1",
        "article",
        "works_stats",
        [{"a": "A-ALICE", "n": "Alice Author", "o": "0000-0002-1111"}],
    ),
    ("W-GAP2", "Gap Two Untyped", 2023, "9999-9999", None, None, "works_stats", []),
    # Spreadsheet-active leading titles: each cell must gain the ' prefix.
    ("WF-ADD", "+Add", 2023, "1234-5678", None, "article", "works_stats", []),
    ("WF-SUB", "-Sub", 2023, "1234-5678", None, "article", "works_stats", []),
    ("WF-EQ", "=Danger", 2023, "1234-5678", None, "article", "works_stats", []),
    ("WF-AT", "@At", 2023, "1234-5678", None, "article", "works_stats", []),
    # Gate fillers: author-sweep source, DOI held by Pure, excluded type,
    # pre-window year, author-attributed row in a venue outside the group.
    ("W-SWEEP", "Sweep Only", 2024, "1234-5678", "10.9.0/6", "article", "author-sweep", []),
    ("W-MATCHED", "Matched", 2023, "1234-5678", "10.0.0/w1", "article", "works_stats", []),
    ("W-PRE", "Preprint", 2024, "1234-5678", "10.9.0/9", "preprint", "works_stats", []),
    ("W-OLD", "Old", 2019, "1234-5678", "10.9.0/8", "article", "works_stats", []),
    (
        "W-GHOST",
        "Ghost",
        2024,
        "7777-7777",
        "10.9.0/7",
        "article",
        "works_stats",
        [{"a": "A-ALICE", "n": "Alice Author", "o": None}],
    ),
]

RAW_FORMULA_TITLES = ["+Add", "-Sub", "=Danger", "@At"]
#: The served cells: spreadsheet-active leading characters gain a ' prefix.
FORMULA_TITLES = ["'" + t for t in RAW_FORMULA_TITLES]


def _oa_work(inst_id, spec) -> OpenalexWork:
    w_id, title, year, venue, doi, work_type, source, authorships = spec
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
        source=source,
    )


@pytest.fixture
async def exports_api(client, db, institution_factory):
    """ut: the Publisher One group spans journals 1234-5678 + 9999-9999
    with store rows exercising every gate and the formula guard, alice's
    roster/canon data, and enriched (rebuild-folded) fields on W-GAP1."""
    ut = await institution_factory(code="ut", data_window_start=2020)
    db.add_all(
        [
            journal_factory("1234-5678", publisher_name=PUB),
            journal_factory("9999-9999", publisher_name=PUB),
        ]
    )
    # Above the browsable cutoff so the publisher group resolves.
    db.add_all(
        JournalFlags(institution_id=ut.id, issn_l=issn, works_count=1, works_window_plus=5)
        for issn in ("1234-5678", "9999-9999")
    )
    db.add(JiscPublisher(id=1, name=PUB, ror="https://ror.org/pub01"))
    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    db.add(run)
    await db.flush()
    db.add(
        Work(
            institution_id=ut.id,
            pure_uuid="w1",
            title="Work w1",
            norm_title="work w1",
            year=2023,
            doi_normalized="10.0.0/w1",
            journal_issn_l="1234-5678",
            first_seen_run=run.id,
            last_seen_run=run.id,
        )
    )
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
    works = [_oa_work(ut.id, spec) for spec in STORE_WORKS]
    for w in works:
        if w.w_id == "W-GAP1":
            # Raw-payload fields live as store columns (the rebuild folds
            # the latest source_record version in; its own test pins that).
            w.publication_date = "2024-05-01"
            w.pdf_url = "https://oa.example/gap1.pdf"
            w.landing_page_url = "https://primary.example/gap1"
            w.institution_rors = "https://ror.org/02"
    db.add_all(works)
    # Author attribution probes the openalex_work_authors edge table.
    db.add_all(pair_rows(*works))
    await db.commit()
    return client


def _rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def _titles(text: str) -> list[str]:
    return [row["title"] for row in _rows(text)]


@requires_db
async def test_journal_gap_csv_rows_quoting_and_formula_guard(exports_api):
    r = await exports_api.get("/api/v1/ut/journals/1234-5678/openalex-only.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"] == 'attachment; filename="1234-5678-openalex-only.csv"'
    rows = _rows(r.text)
    assert list(rows[0]) == list(CSV_COLUMNS)
    # Gates mirror the on-screen card: author-sweep, DOI-matched-Pure,
    # excluded-type, out-of-window and other-venue rows stay out. Rows
    # sort year desc, then title (case-insensitive).
    assert _titles(r.text) == ['Gap, "One"', *FORMULA_TITLES]
    # The csv layer quotes embedded commas/quotes; the parse round-trips.
    gap1 = rows[0]
    assert gap1["title"] == 'Gap, "One"'
    assert gap1["openalex_id"] == "W-GAP1"
    assert gap1["publication_year"] == "2024"
    # Raw-payload fields are store columns (the rebuild folds the latest
    # source_record version in; the works-stats rebuild test pins that).
    assert gap1["publication_date"] == "2024-05-01"
    assert gap1["pdf_url"] == "https://oa.example/gap1.pdf"
    assert gap1["landing_page_url"] == "https://primary.example/gap1"
    assert gap1["institution_rors"] == "https://ror.org/02"
    assert gap1["doi"] == "10.9.0/1"
    assert gap1["doi_url"] == "https://doi.org/10.9.0/1"
    assert gap1["authors"] == "Alice Author"
    assert gap1["authors_openalex_ids"] == "A-ALICE"
    assert gap1["authors_orcids"] == "0000-0002-1111"
    assert gap1["ut_authors"] == "Alice Author"
    assert gap1["ut_affiliations"] == f"{FACULTY} / Group X / DSI"
    assert gap1["publisher_name"] == PUB
    assert gap1["publisher_ror"] == "https://ror.org/pub01"
    assert gap1["in_pure"] == "false"
    by_title = {row["title"]: row for row in rows}
    # Spreadsheet-active leading characters get a ' prefix; the csv layer
    # keeps the rest of the cell verbatim.
    assert by_title["'=Danger"]["work_type"] == "article"
    assert by_title['Gap, "One"']["oa_status"] == "gold"


@requires_db
async def test_publisher_and_author_works_csv(exports_api):
    r = await exports_api.get("/api/v1/ut/publishers/Publisher One/openalex-only.csv")
    assert r.status_code == 200
    assert (
        r.headers["content-disposition"] == 'attachment; filename="Publisher-One-openalex-only.csv"'
    )
    rows = {row["title"]: row for row in _rows(r.text)}
    # Both group journals contribute; the gated rows stay out.
    assert set(rows) == {'Gap, "One"', "Gap Two Untyped", *FORMULA_TITLES}
    gap2 = rows["Gap Two Untyped"]
    assert gap2["issn_l"] == "9999-9999"
    # No raw payload stored for W-GAP2: raw-derived cells stay empty.
    assert gap2["publication_date"] == ""
    assert gap2["pdf_url"] == ""
    assert gap2["institution_rors"] == ""
    assert gap2["doi"] == ""
    # NULL work type survives the gate and lands empty.
    assert gap2["work_type"] == ""
    assert gap2["ut_authors"] == ""
    assert gap2["publisher_name"] == PUB
    unknown_pub = await exports_api.get("/api/v1/ut/publishers/No Such Publisher/openalex-only.csv")
    assert unknown_pub.status_code == 404

    missed = await exports_api.get(
        "/api/v1/ut/authors/alice-uuid/works.csv", params={"scope": "missed"}
    )
    assert missed.status_code == 200
    assert (
        missed.headers["content-disposition"]
        == 'attachment; filename="alice-uuid-works-missed.csv"'
    )
    mrows = {row["title"]: row for row in _rows(missed.text)}
    # Attribution is author-scoped, not venue-scoped: the group-external
    # ghost row counts; unattributed rows have no authorship.
    assert set(mrows) == {'Gap, "One"', "Ghost"}
    ghost = mrows["Ghost"]
    assert ghost["openalex_id"] == "W-GHOST"
    assert ghost["ut_authors"] == "Alice Author"
    # No journal row for 7777-7777: publisher context degrades to empty.
    assert ghost["publisher_name"] == "" and ghost["publisher_ror"] == ""
    assert ghost["in_pure"] == "false"

    canon = await exports_api.get(
        "/api/v1/ut/authors/alice-uuid/works.csv", params={"scope": "canon"}
    )
    assert canon.status_code == 200
    assert (
        canon.headers["content-disposition"] == 'attachment; filename="alice-uuid-works-canon.csv"'
    )
    crows = _rows(canon.text)
    assert [row["title"] for row in crows] == ["Work w1"]
    work = crows[0]
    # OpenAlex-side columns stay empty except the DOI; the page author is
    # the sole UT author.
    assert work["openalex_id"] == "" and work["publication_date"] == ""
    assert work["doi"] == "10.0.0/w1"
    assert work["publication_year"] == "2023"
    assert work["journal_title"] == "Journal 1234-5678"
    assert work["publisher_name"] == PUB
    assert work["publisher_ror"] == "https://ror.org/pub01"
    assert work["ut_authors"] == "Alice Author"
    assert work["ut_affiliations"] == f"{FACULTY} / Group X / DSI"
    assert work["in_pure"] == "true"


@requires_db
async def test_csv_error_paths_and_year_filter(exports_api):
    assert (
        await exports_api.get("/api/v1/ut/journals/0000-0000/openalex-only.csv")
    ).status_code == 404
    bad_scope = await exports_api.get(
        "/api/v1/ut/authors/alice-uuid/works.csv", params={"scope": "everything"}
    )
    assert bad_scope.status_code == 400
    assert (await exports_api.get("/api/v1/ut/authors/nope/works.csv")).status_code == 404

    # The year lens narrows the CSV rows like the on-screen card.
    full = await exports_api.get("/api/v1/ut/journals/1234-5678/openalex-only.csv")
    assert _titles(full.text) == ['Gap, "One"', *FORMULA_TITLES]
    to2023 = await exports_api.get(
        "/api/v1/ut/journals/1234-5678/openalex-only.csv",
        params={"year_from": 2020, "year_to": 2023},
    )
    assert _titles(to2023.text) == FORMULA_TITLES
    from2024 = await exports_api.get(
        "/api/v1/ut/journals/1234-5678/openalex-only.csv", params={"year_from": 2024}
    )
    assert _titles(from2024.text) == ['Gap, "One"']
