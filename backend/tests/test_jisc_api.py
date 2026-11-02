"""Jisc Open Policy Finder API surface: green_oa search filter + facet,
detail green_oa block, boundary validation (422)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import journal_factory, requires_db
from journal_browser.harvest.denorm import MATERIALIZE_SQL
from journal_browser.models import Institution

HARVESTED_AT = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)

POLICY = {
    "routes": {
        "submitted": {
            "locations": ["any repository"],
            "repositories": ["arXiv"],
            "licenses": [],
            "embargo_months": None,
            "conditions": [],
            "additional_oa_fee": "no",
        },
        "accepted": {
            "locations": ["this repository"],
            "repositories": [],
            "licenses": ["cc-by"],
            "embargo_months": 12,
            "conditions": ["published source must be cited"],
            "additional_oa_fee": None,
        },
        "published": {
            "locations": ["this journal"],
            "repositories": [],
            "licenses": [],
            "embargo_months": None,
            "conditions": [],
            "additional_oa_fee": "yes",
        },
    },
    "open_access_prohibited": False,
    "internal_moniker": "Test Publisher",
    "urls": [{"url": "https://example.com/policy", "description": "publisher policy"}],
    "policy_uri": "https://openpolicyfinder.jisc.ac.uk/publication/123",
}


@pytest.fixture
async def api(client, db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        session.add_all(
            [
                # Best route = accepted; carries the full display object.
                journal_factory(
                    "1111-1111",
                    title="Accepted Route Journal",
                    search_text=None,
                    jisc_in_opf=True,
                    jisc_allows_sa_submitted=False,
                    jisc_allows_sa_accepted=True,
                    jisc_allows_sa_published=False,
                    jisc_embargo_accepted_months=12,
                    jisc_policy=POLICY,
                    jisc_harvested_at=HARVESTED_AT,
                ),
                # Best route = submitted.
                journal_factory(
                    "2222-2222",
                    title="Submitted Route Journal",
                    search_text=None,
                    jisc_in_opf=True,
                    jisc_allows_sa_submitted=True,
                    jisc_allows_sa_accepted=False,
                    jisc_allows_sa_published=False,
                ),
                # Swept, OA prohibited outright: no permitted route.
                journal_factory(
                    "3333-3333",
                    title="Prohibited Journal",
                    search_text=None,
                    jisc_in_opf=True,
                    jisc_oa_prohibited=True,
                    jisc_allows_sa_submitted=False,
                    jisc_allows_sa_accepted=False,
                    jisc_allows_sa_published=False,
                ),
                # Best route = published.
                journal_factory(
                    "4444-4444",
                    title="Published Route Journal",
                    search_text=None,
                    jisc_in_opf=True,
                    jisc_allows_sa_submitted=False,
                    jisc_allows_sa_accepted=False,
                    jisc_allows_sa_published=True,
                ),
                # Never swept: every jisc column NULL.
                journal_factory("5555-5555", title="Unswept Journal", search_text=None),
                # Prohibited despite a free route: prohibition wins over routes.
                journal_factory(
                    "6666-6666",
                    title="Prohibited With Route Journal",
                    search_text=None,
                    jisc_in_opf=True,
                    jisc_oa_prohibited=True,
                    jisc_allows_sa_submitted=True,
                ),
            ]
        )
        await session.commit()
        home = Institution(name="University of Twente", code="ut", active=True)
        session.add(home)
        await session.flush()
        await session.execute(MATERIALIZE_SQL, {"iid": home.id})
        await session.execute(
            text("UPDATE journal_flags SET works_window_plus = 10 WHERE institution_id = :iid"),
            {"iid": home.id},
        )
        await session.commit()
    return client


def _issns(body: dict) -> set[str]:
    return {i["issn_l"] for i in body["items"]}


@requires_db
async def test_detail_green_oa_block(api):
    r = await api.get("/api/v1/ut/journals/1111-1111")
    assert r.status_code == 200
    body = r.json()
    harvested = body["green_oa"].pop("harvested_at")
    assert harvested.startswith("2026-11-02T12:00")
    assert body["green_oa"] == {
        "in_opf": True,
        "oa_prohibited": False,
        "routes": POLICY["routes"],
        "internal_moniker": "Test Publisher",
        "urls": POLICY["urls"],
        "policy_uri": POLICY["policy_uri"],
    }
    assert body["attribution"]["green_oa"]["source"] == "Jisc Open Policy Finder"
    assert body["attribution"]["green_oa"]["caveat_codes"] == [
        "jisc-policy-currency",
        "jisc-cc-by-nc-nd",
    ]


@requires_db
async def test_detail_green_oa_null_unswept(api):
    body = (await api.get("/api/v1/ut/journals/5555-5555")).json()
    assert body["green_oa"] is None


@requires_db
async def test_search_green_oa_filter(api):
    accepted = await api.get("/api/v1/ut/journals", params={"green_oa": "accepted"})
    assert _issns(accepted.json()) == {"1111-1111"}
    assert _issns(
        (await api.get("/api/v1/ut/journals", params={"green_oa": "submitted"})).json()
    ) == {"2222-2222"}
    assert _issns(
        (await api.get("/api/v1/ut/journals", params={"green_oa": "published"})).json()
    ) == {"4444-4444"}


@requires_db
async def test_search_green_oa_none_excludes_unswept(api):
    body = (await api.get("/api/v1/ut/journals", params={"green_oa": "none"})).json()
    assert _issns(body) == {"3333-3333", "6666-6666"}


@requires_db
async def test_search_green_oa_prohibited_excluded_from_routes(api):
    body = (await api.get("/api/v1/ut/journals", params={"green_oa": "submitted"})).json()
    assert "6666-6666" not in _issns(body)


@requires_db
async def test_search_green_oa_junk_422(api):
    r = await api.get("/api/v1/ut/journals", params={"green_oa": "banana"})
    assert r.status_code == 422


@requires_db
async def test_facet_green_oa_bucket(api):
    plain = (await api.get("/api/v1/ut/journals")).json()
    assert plain["facets"]["green_oa"] == {
        "submitted": 1,
        "accepted": 1,
        "published": 1,
        "none": 2,
    }
    # Drop-own-dimension: counts under an active green_oa filter show what
    # selecting each value would yield, i.e. the unfiltered distribution.
    filtered = (await api.get("/api/v1/ut/journals", params={"green_oa": "accepted"})).json()
    assert filtered["facets"]["green_oa"] == plain["facets"]["green_oa"]
