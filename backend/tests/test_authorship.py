"""Authorship aggregates (who authors a venue's works) and the CRIS-gap
queries (OpenAlex store works whose DOI matches no Pure work) behind the
journal/publisher/orgunit detail cards."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import journal_factory, requires_db
from journal_browser.db import get_session
from journal_browser.main import app
from journal_browser.models import Author, HarvestRun, OpenalexWork, Work, WorkPureAuthor
from journal_browser.services import authorship

EEMCS = "Faculty of Electrical Engineering, Mathematics and Computer Science"
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
    source_type=None,
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
        authorships=authorships,
        author_aids=sorted({a["a"].lower() for a in authorships if a.get("a")}),
        source=source,
        source_type=source_type,
    )


@pytest.fixture
async def authorship_db(db, institution_factory):
    """ut: journal 1234-5678 with works and authors arranged to pin the
    distinct-work counting rules, plus store rows exercising every gap
    gate (matched DOI, excluded type, NULL type, repository source,
    window, venue)."""
    ut = await institution_factory(code="ut", data_window_start=WINDOW_START)
    db.add(journal_factory("1234-5678", publisher_name="Publisher One"))
    db.add(journal_factory("9999-9999"))
    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    db.add(run)
    await db.flush()

    def _work(uuid, year, issn="1234-5678", work_type="info:eu-repo/semantics/article", doi=None):
        return Work(
            institution_id=ut.id,
            pure_uuid=uuid,
            title=f"Work {uuid}",
            norm_title=f"work {uuid}",
            year=year,
            doi_normalized=doi,
            work_type=work_type,
            journal_issn_l=issn,
            first_seen_run=run.id,
            last_seen_run=run.id,
        )

    db.add_all(
        [
            _work("w1", 2023, doi="10.0.0/w1"),
            _work("w2", 2022, doi="10.0.0/w2"),
            _work("w3", 2024, doi="10.0.0/w3"),
            _work("w4", 2023),  # no author edges
            _work("wex", 2023, work_type="info:eu-repo/semantics/bookchapter"),
            _work("wout", 2019),  # outside the window
            _work("wret", 2023),  # retired below
            _work("wother", 2023, issn="9999-9999"),  # other journal
        ]
    )
    await db.flush()
    wret = await db.get(Work, (ut.id, "wret"))
    from datetime import UTC, datetime

    wret.retired_at = datetime.now(UTC)
    db.add_all(
        [
            Author(
                institution_id=ut.id,
                pure_uuid="alice-uuid",
                name="Alice Author",
                faculty=EEMCS,
                research_group="Group X",
                openalex_ids=["a-alice"],
                n_works=2,
                confirmed=True,
            ),
            Author(
                institution_id=ut.id,
                pure_uuid="bob-uuid",
                name="Bob Author",
                faculty=EEMCS,
                research_group="Group Y",
                openalex_ids=["a-bob"],
                n_works=1,
                confirmed=True,
            ),
            Author(
                institution_id=ut.id,
                pure_uuid="carol-uuid",
                name="Carol Author",
                faculty="Faculty of Behavioural Sciences",
                research_group="Group Z",
                n_works=1,
                confirmed=True,
            ),
            WorkPureAuthor(institution_id=ut.id, work_pure_uuid="w1", person_uuid="alice-uuid"),
            WorkPureAuthor(institution_id=ut.id, work_pure_uuid="w2", person_uuid="bob-uuid"),
            WorkPureAuthor(institution_id=ut.id, work_pure_uuid="w3", person_uuid="alice-uuid"),
            WorkPureAuthor(institution_id=ut.id, work_pure_uuid="w3", person_uuid="carol-uuid"),
            WorkPureAuthor(institution_id=ut.id, work_pure_uuid="wex", person_uuid="alice-uuid"),
            WorkPureAuthor(institution_id=ut.id, work_pure_uuid="wret", person_uuid="alice-uuid"),
            WorkPureAuthor(institution_id=ut.id, work_pure_uuid="wother", person_uuid="alice-uuid"),
            WorkPureAuthor(institution_id=ut.id, work_pure_uuid="wout", person_uuid="alice-uuid"),
        ]
    )
    db.add_all(
        [
            # venue gaps: unmatched DOI + DOI-less row (NULL type stays);
            # Gap One names a roster author so the item-level ut
            # attribution has something to match
            _oa_work(
                ut.id,
                "W-gap1",
                doi="10.9.0/1",
                title="Gap One",
                year=2024,
                authorships=[{"a": "A-ALICE", "n": "Alice Author", "o": "0000-0002-1111"}],
            ),
            _oa_work(ut.id, "W-gap2", title="Gap Two Untyped", year=2023, work_type=None),
            # gated rows: matched DOI, excluded type, repository source
            # (a Zenodo/Pure-RIS copy is no Pure gap), out of window, other venue
            _oa_work(ut.id, "W-matched", doi="10.0.0/w1", title="Matched", year=2023),
            _oa_work(
                ut.id, "W-pre", doi="10.9.0/9", title="Preprint", year=2024, work_type="preprint"
            ),
            _oa_work(
                ut.id,
                "W-data",
                doi="10.9.0/4",
                title="Dataset",
                year=2024,
                work_type="dataset",
                authorships=[{"a": "A-ALICE"}],
            ),
            _oa_work(
                ut.id,
                "W-repo",
                doi="10.9.0/5",
                title="Repo Copy",
                year=2024,
                source_type="repository",
                authorships=[{"a": "A-ALICE"}],
            ),
            _oa_work(ut.id, "W-old", doi="10.9.0/8", title="Old", year=2019),
            # author-sweep row: in-venue, in-window, unmatched DOI, but
            # harvested from an author profile — OpenAlex attributes it
            # elsewhere, so the venue gap card must not count it
            _oa_work(
                ut.id,
                "W-sweep",
                doi="10.9.0/6",
                title="Sweep Only",
                year=2024,
                source="author-sweep",
            ),
            _oa_work(
                ut.id,
                "W-other",
                doi="10.9.0/7",
                title="Other Venue",
                year=2024,
                authorships=[{"a": "A-ALICE"}],
            ),
        ]
    )
    # fix the other-venue row's venue
    await db.flush()
    other = await db.get(OpenalexWork, (ut.id, "W-other"))
    other.venue_issn_l = "9999-9999"
    db.add_all(
        [
            # unit-attributed rows: one via a-alice, one naming two unit ids
            # (must count once), one attributed but DOI-matched (gate wins)
            _oa_work(
                ut.id,
                "W-u1",
                doi="10.9.1/1",
                title="Unit Gap One",
                year=2024,
                venue="7777-7777",
                authorships=[{"a": "A-ALICE"}],
            ),
            _oa_work(
                ut.id,
                "W-u2",
                doi="10.9.1/2",
                title="Unit Gap Two",
                year=2023,
                venue="7777-7777",
                authorships=[{"a": "A-ALICE"}, {"a": "A-BOB"}],
            ),
            _oa_work(
                ut.id,
                "W-u3",
                doi="10.0.0/w2",
                title="Unit Matched",
                year=2022,
                venue="7777-7777",
                authorships=[{"a": "A-ALICE"}],
            ),
        ]
    )
    await db.commit()

    async def _override():
        async with async_sessionmaker(db.bind, expire_on_commit=False)() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    try:
        yield ut
    finally:
        app.dependency_overrides.clear()


@requires_db
async def test_venue_authorship_counts_distinct_works(authorship_db, db):
    ut = authorship_db
    async with async_sessionmaker(db.bind, expire_on_commit=False)() as session:
        inst = await session.get(type(ut), ut.id)
        out = await authorship.venue_authorship(session, inst, issn_l="1234-5678")
    # w1, w2, w3 and the book-chapter wex carry UT author edges after
    # gating (book chapters are app output; w4 none, wout/wret/wother drop
    # via window/retired/venue gates)
    assert out["n_ut_works"] == 4
    # distinct works per faculty: alice+bob+carol cover EEMCS over
    # w1..w3+wex (w3 counted once despite two EEMCS authors)
    assert out["faculties"] == [
        {"name": EEMCS, "works": 4},
        {"name": "Faculty of Behavioural Sciences", "works": 1},
    ]
    assert out["research_groups"] == [
        {"name": "Group X", "works": 3},
        {"name": "Group Y", "works": 1},
        {"name": "Group Z", "works": 1},
    ]
    # count desc, then name asc on ties
    assert [(a["name"], a["works"]) for a in out["top_authors"]] == [
        ("Alice Author", 3),
        ("Bob Author", 1),
        ("Carol Author", 1),
    ]
    assert all(a["pure_uuid"].endswith("-uuid") for a in out["top_authors"])


@requires_db
async def test_venue_openalex_only_applies_gates(authorship_db, db):
    ut = authorship_db
    async with async_sessionmaker(db.bind, expire_on_commit=False)() as session:
        inst = await session.get(type(ut), ut.id)
        out = await authorship.venue_openalex_only(session, inst, issn_l="1234-5678")
    assert out["available"] is True
    # matched-DOI, preprint, dataset, repository-sourced, out-of-window,
    # and other-venue rows drop; the DOI-less NULL-type row stays
    assert out["total"] == 2
    assert [i["title"] for i in out["items"]] == ["Gap One", "Gap Two Untyped"]
    assert out["items"][1]["doi"] is None
    assert out["items"][1]["work_type"] is None
    # items carry work identity, authorships, roster attribution, and
    # venue context
    first = out["items"][0]
    assert first["openalex_id"] == "W-gap1"
    assert first["openalex_url"] == "https://openalex.org/W-gap1"
    assert first["authors"] == [
        {"openalex_id": "A-ALICE", "name": "Alice Author", "orcid": "0000-0002-1111"}
    ]
    assert first["ut_authors"] == [
        {
            "name": "Alice Author",
            "orcid": None,
            "faculty": EEMCS,
            "research_group": "Group X",
            "institute": None,
        }
    ]
    assert first["journal_issn_l"] == "1234-5678"
    assert first["journal_title"] == "Journal One"
    assert first["publisher_name"] == "Publisher One"
    # the legacy venue key stays (store venue_name)
    assert first["venue"] == "Journal One"
    # the unattributed row keeps the new keys but empty lists
    assert out["items"][1]["authors"] == []
    assert out["items"][1]["ut_authors"] == []
    assert out["items"][1]["publisher_name"] == "Publisher One"


@requires_db
async def test_venue_openalex_only_publisher_scope(authorship_db, db):
    """The publisher path: one issn set covering both journals."""
    ut = authorship_db
    async with async_sessionmaker(db.bind, expire_on_commit=False)() as session:
        inst = await session.get(type(ut), ut.id)
        out = await authorship.venue_openalex_only(session, inst, issns=["1234-5678", "9999-9999"])
    # venue gaps (2) + the other-venue row, now in scope
    assert out["total"] == 3
    assert out["items"][0]["title"] == "Gap One"


@requires_db
async def test_author_ids_openalex_only_counts_work_once(authorship_db, db):
    ut = authorship_db
    async with async_sessionmaker(db.bind, expire_on_commit=False)() as session:
        inst = await session.get(type(ut), ut.id)
        out = await authorship.author_ids_openalex_only(session, inst, ["a-alice", "a-bob"])
    # W-u1 (alice) + W-u2 (alice+bob, counted once); W-u3's DOI matches a
    # pure work and W-other sits in another venue but IS attributed —
    # attribution is unit-wide, not venue-scoped, so it counts too.
    # W-gap1 names alice as well and counts here (venue gaps are not
    # author-scoped, but attribution is). Alice's dataset and
    # repository-sourced rows drop via the type/source gates.
    assert out["total"] == 4
    assert sorted(i["title"] for i in out["items"]) == [
        "Gap One",
        "Other Venue",
        "Unit Gap One",
        "Unit Gap Two",
    ]


@requires_db
async def test_gaps_unavailable_without_store(db, institution_factory):
    """No store rows for the institution -> available False, not a zero."""
    ut = await institution_factory(code="ut", data_window_start=WINDOW_START)
    await db.commit()
    async with async_sessionmaker(db.bind, expire_on_commit=False)() as session:
        inst = await session.get(type(ut), ut.id)
        out = await authorship.venue_openalex_only(session, inst, issn_l="1234-5678")
        assert out == {"total": 0, "items": [], "available": False}
        unit = await authorship.author_ids_openalex_only(session, inst, ["a-x"])
        assert unit["available"] is False


@requires_db
async def test_journal_detail_carries_new_fields(authorship_db, db):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/v1/ut/journals/1234-5678")
    assert r.status_code == 200
    body = r.json()
    assert body["ut_authorship"]["n_ut_works"] == 4
    assert body["openalex_only"]["total"] == 2
    assert body["openalex_only"]["available"] is True
