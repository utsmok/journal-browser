"""Search API tests: corpus cutoff (owner decision 2026-10-23)."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import requires_db
from journal_browser.db import get_session
from journal_browser.harvest.denorm import MATERIALIZE_SQL
from journal_browser.main import app
from journal_browser.models import Institution, Journal


def _journal(issn_l: str, **kw) -> Journal:
    base = dict(
        issn_l=issn_l,
        title=f"Journal {issn_l}",
        type="journal",
        is_oa=False,
        is_in_doaj=False,
        in_scimago=False,
        last_active_year=None,
        works_2020_plus=0,
    )
    base.update(kw)
    return Journal(**base)


@pytest.fixture
async def api(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    async with maker() as session:
        session.add_all(
            [
                # At the cutoff boundary: exactly 4 works stays in.
                _journal("1111-1111", works_2020_plus=4),
                _journal("2222-2222", works_2020_plus=1000),
                # Dropped: 3 works or fewer.
                _journal("3333-3333", works_2020_plus=3),
                _journal("4444-4444", works_2020_plus=0),
                # Dropped regardless of works: not a journal type.
                _journal("5555-5555", type="repository", works_2020_plus=50),
            ]
        )
        await session.commit()
        home = Institution(
            name="University of Twente", code="ut", active=True, is_default=True
        )
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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client
    app.dependency_overrides.clear()


@requires_db
async def test_cutoff_excludes_low_activity_journals(api):
    r = await api.get("/api/v1/journals")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    issns = {i["issn_l"] for i in body["items"]}
    assert issns == {"1111-1111", "2222-2222"}


@requires_db
async def test_scope_param_is_gone(api):
    # Unknown query params are ignored; the response carries no badge field.
    plain = (await api.get("/api/v1/journals")).json()
    scoped = (await api.get("/api/v1/journals", params={"scope": "all"})).json()
    assert scoped["total"] == plain["total"] == 2
    assert "in_quality_bar" not in plain["items"][0]


@requires_db
async def test_facets_reflect_cutoff(api):
    body = (await api.get("/api/v1/journals")).json()
    assert sum(body["facets"]["oa"].values()) == 2
    assert body["facets"]["doaj"]["true"] == 0
