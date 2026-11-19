"""Keyword search rank: the institution's own works count (journal_flags)
breaks ties toward journals UT publishes in (decision 23), and the fuzzy
fallback stays gated on the exact query returning nothing."""

import pytest

from conftest import journal_factory, requires_db
from journal_browser.models import Institution, JournalFlags


@pytest.fixture
async def rank_api(client, db_engine, db):
    """pg_trgm (the fuzzy operator) plus two identically-titled journals —
    one with UT works, one without — so FTS rank, prefix tier and global
    prominence are equal and the institution nudge alone decides."""
    async with db_engine.begin() as conn:
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    ut = Institution(name="University of Twente", code="ut", active=True, data_window_start=2020)
    db.add(ut)
    await db.flush()
    common = {"title": "Water Management Reports", "search_text": "Water Management Reports"}
    db.add_all(
        [
            journal_factory("1111-2222", works_count=5000, **common),
            journal_factory("3333-4444", works_count=5000, **common),
            journal_factory(
                "5555-6666",
                title="Water Management X",
                search_text="Water Management X",
                works_count=5000,
            ),
        ]
    )
    await db.flush()
    db.add_all(
        [
            JournalFlags(
                institution_id=ut.id, issn_l="1111-2222", works_count=4, works_window_plus=10
            ),
            JournalFlags(
                institution_id=ut.id, issn_l="3333-4444", works_count=0, works_window_plus=10
            ),
            JournalFlags(
                institution_id=ut.id, issn_l="5555-6666", works_count=0, works_window_plus=10
            ),
        ]
    )
    await db.commit()
    # search_vector is a persisted generated column over search_text; the
    # identical titles give identical FTS ranks, prefix tiers and global
    # prominence, so the institution nudge alone decides.
    return client


@requires_db
async def test_institution_works_break_ties(rank_api):
    r = await rank_api.get("/api/v1/ut/journals", params={"q": "water management"})
    assert r.status_code == 200
    body = r.json()
    assert body["fuzzy"] is False  # exact FTS has results: no fallback
    issns = [i["issn_l"] for i in body["items"]]
    # Identical titles: rank, prefix tier and global prominence tie; the
    # UT-published journal (works_count 4) must come first.
    assert issns[0] == "1111-2222"
    assert set(issns) == {"1111-2222", "3333-4444", "5555-6666"}


@requires_db
async def test_fuzzy_only_fires_without_exact_hits(rank_api):
    r = await rank_api.get("/api/v1/ut/journals", params={"q": "water management"})
    assert r.json()["fuzzy"] is False
    miss = await rank_api.get("/api/v1/ut/journals", params={"q": "xzqxjqzz"})
    assert miss.status_code == 200
    assert miss.json()["fuzzy"] is True
    assert miss.json()["total"] == 0
