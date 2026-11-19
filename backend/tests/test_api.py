"""Search API tests: corpus cutoff (owner decision 2026-10-23)."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import journal_factory, requires_db
from journal_browser.harvest.denorm import MATERIALIZE_SQL
from journal_browser.models import Institution


@pytest.fixture
async def api(client, db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        session.add_all(
            [
                # At the cutoff boundary: exactly 4 works stays in.
                journal_factory("1111-1111", works_2020_plus=4, search_text=None),
                journal_factory("2222-2222", works_2020_plus=1000, search_text=None),
                # Dropped: 3 works or fewer.
                journal_factory("3333-3333", works_2020_plus=3, search_text=None),
                journal_factory("4444-4444", works_2020_plus=0, search_text=None),
                # Dropped regardless of works: not a journal type.
                journal_factory(
                    "5555-5555", type="repository", works_2020_plus=50, search_text=None
                ),
            ]
        )
        await session.commit()
        home = Institution(name="University of Twente", code="ut", active=True)
        session.add(home)
        await session.flush()
        # The cutoff lives on journal_flags.works_window_plus per institution.
        await session.execute(MATERIALIZE_SQL, {"iid": home.id})
        await session.execute(
            text(
                "UPDATE journal_flags f SET works_window_plus = j.works_2020_plus"
                " FROM journals j WHERE j.issn_l = f.issn_l"
                " AND f.institution_id = :iid"
            ),
            {"iid": home.id},
        )
        await session.commit()
    return client


@requires_db
async def test_cutoff_excludes_low_activity_journals(api):
    r = await api.get("/api/v1/ut/journals")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    issns = {i["issn_l"] for i in body["items"]}
    assert issns == {"1111-1111", "2222-2222"}


@requires_db
async def test_scope_param_is_gone(api):
    # Unknown query params are ignored; the response carries no badge field.
    plain = (await api.get("/api/v1/ut/journals")).json()
    scoped = (await api.get("/api/v1/ut/journals", params={"scope": "all"})).json()
    assert scoped["total"] == plain["total"] == 2
    assert "in_quality_bar" not in plain["items"][0]


@requires_db
async def test_facets_reflect_cutoff(api):
    body = (await api.get("/api/v1/ut/journals")).json()
    assert sum(body["facets"]["oa"].values()) == 2
    assert body["facets"]["doaj"]["true"] == 0


@requires_db
async def test_nonjournal_venues_browse_with_ut_works(api, db_engine):
    """Other OpenAlex venue types join the corpus once the institution has
    >= 1 work in them (owner decision 2026-11-04); the corpus cutoff
    (works_window_plus > 3) keeps applying to plain journals only. The
    fixture's repository (works_window_plus=50, zero institution works)
    must stay hidden."""
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        session.add(
            journal_factory(
                "6666-6666",
                type="book series",
                title="Lecture notes in computer science",
                search_text="Lecture notes in computer science",
            )
        )
        await session.commit()
        await session.execute(
            text(
                "INSERT INTO journal_flags (institution_id, issn_l, works_count,"
                " works_window_plus) SELECT id, '6666-6666', 7, 200 FROM institutions"
                " WHERE code = 'ut'"
            )
        )
        await session.commit()

    body = (await api.get("/api/v1/ut/journals")).json()
    by_issn = {i["issn_l"]: i for i in body["items"]}
    assert set(by_issn) == {"1111-1111", "2222-2222", "6666-6666"}
    assert by_issn["6666-6666"]["pub_type"] == "book series"
    # Facet counts over the widened corpus, sorted by count then name.
    assert body["facets"]["pub_type"] == {"journal": 2, "book series": 1}

    # The venue-type filter narrows to the series; its own facet keeps the
    # full distribution (drop-own-dimension).
    filtered = (await api.get("/api/v1/ut/journals", params={"pub_type": "book series"})).json()
    assert [i["issn_l"] for i in filtered["items"]] == ["6666-6666"]
    assert filtered["facets"]["pub_type"] == {"journal": 2, "book series": 1}

    # Free text finds the series by title, like any journal.
    hits = (await api.get("/api/v1/ut/journals", params={"q": "lecture notes"})).json()
    assert [i["issn_l"] for i in hits["items"]] == ["6666-6666"]
