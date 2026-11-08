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
    authorships=None,
    venue="1234-5678",
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
    )


@pytest.fixture
async def authorship_db(db, institution_factory):
    """ut: journal 1234-5678 with works and authors arranged to pin the
    distinct-work counting rules, plus store rows exercising every gap
    gate (matched DOI, excluded type, NULL type, window, venue)."""
    ut = await institution_factory(code="ut", data_window_start=WINDOW_START)
    db.add(journal_factory("1234-5678"))
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
            # venue gaps: unmatched DOI + DOI-less row (NULL type stays)
            _oa_work(ut.id, "W-gap1", doi="10.9.0/1", title="Gap One", year=2024),
            _oa_work(ut.id, "W-gap2", title="Gap Two Untyped", year=2023, work_type=None),
            # gated rows: matched DOI, excluded type, out of window, other venue
            _oa_work(ut.id, "W-matched", doi="10.0.0/w1", title="Matched", year=2023),
            _oa_work(
                ut.id, "W-pre", doi="10.9.0/9", title="Preprint", year=2024, work_type="preprint"
            ),
            _oa_work(ut.id, "W-old", doi="10.9.0/8", title="Old", year=2019),
            _oa_work(
                ut.id,
                "W-other",
                doi="10.9.0/7",
                title="Other Venue",
                year=2024,
                authorships=[{"a": "a-alice"}],
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
                authorships=[{"a": "a-alice"}],
            ),
            _oa_work(
                ut.id,
                "W-u2",
                doi="10.9.1/2",
                title="Unit Gap Two",
                year=2023,
                venue="7777-7777",
                authorships=[{"a": "a-alice"}, {"a": "a-bob"}],
            ),
            _oa_work(
                ut.id,
                "W-u3",
                doi="10.0.0/w2",
                title="Unit Matched",
                year=2022,
                venue="7777-7777",
                authorships=[{"a": "a-alice"}],
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
    # w1, w2, w3 carry UT author edges after gating (w4 none, wex/wout/
    # wret/wother drop via type/window/retired/venue gates)
    assert out["n_ut_works"] == 3
    # distinct works per faculty: alice+bob+carol cover EEMCS over
    # w1..w3 (w3 counted once despite two EEMCS authors)
    assert out["faculties"] == [
        {"name": EEMCS, "works": 3},
        {"name": "Faculty of Behavioural Sciences", "works": 1},
    ]
    assert out["research_groups"] == [
        {"name": "Group X", "works": 2},
        {"name": "Group Y", "works": 1},
        {"name": "Group Z", "works": 1},
    ]
    # count desc, then name asc on ties
    assert [(a["name"], a["works"]) for a in out["top_authors"]] == [
        ("Alice Author", 2),
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
    # matched-DOI, preprint, out-of-window, and other-venue rows drop;
    # the DOI-less NULL-type row stays
    assert out["total"] == 2
    assert [i["title"] for i in out["items"]] == ["Gap One", "Gap Two Untyped"]
    assert out["items"][1]["doi"] is None
    assert out["items"][1]["work_type"] is None


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
    # attribution is unit-wide, not venue-scoped, so it counts too
    assert out["total"] == 3
    assert sorted(i["title"] for i in out["items"]) == [
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
    assert body["ut_authorship"]["n_ut_works"] == 3
    assert body["openalex_only"]["total"] == 2
    assert body["openalex_only"]["available"] is True
