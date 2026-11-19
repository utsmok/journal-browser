"""Semantic-search perf rewrite: one ordered HNSW scan serves page and
total (capped at SEMANTIC_TOTAL_CAP). Pins the identity contract: rows and
order unchanged, exact total below the cap, capped total at the cap, and
cursor paging that stops at the cap."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import journal_factory, requires_db
from journal_browser.models import Institution, Journal, JournalFlags
from journal_browser.services.search.similar import (
    SEMANTIC_TOTAL_CAP,
    semantic_search,
)

DIM = 384


def _vec(i: int) -> list[float]:
    return [1.0 if j == i else 0.0 for j in range(DIM)]


async def _seed(engine, journals: list[tuple[str, int]]):
    """One institution plus (issn, vector-index) journal rows with flags;
    distance between distinct basis vectors is 1 (out of the 0.32 range),
    so proximity comes only from identical vectors."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        inst = Institution(code="ut", name="Test U", ror="https://ror.org/test0001", active=True)
        session.add(inst)
        await session.flush()
        for n, (issn, vec_i) in enumerate(journals):
            session.add(
                journal_factory(
                    issn,
                    title=f"Journal {n}",
                    search_text=f"Journal {n}",
                    embedding=_vec(vec_i),
                )
            )
            session.add(
                JournalFlags(
                    institution_id=inst.id,
                    issn_l=issn,
                    works_count=10,
                    works_window_plus=10,
                )
            )
        await session.commit()


@pytest.fixture
async def seeded(db_engine):
    await _seed(
        db_engine,
        [("aaaa-0001", 0), ("aaaa-0002", 0), ("aaaa-0003", 0), ("bbbb-0001", 1)],
    )


@requires_db
async def test_total_exact_and_rows_ordered(db_engine, seeded, monkeypatch):
    """Three same-vector journals sit within the distance cap (total 3),
    the orthogonal one stays out of items and total, order follows the
    (distance, issn_l) key."""
    from journal_browser.services import embeddings

    monkeypatch.setattr(embeddings, "encode_query", lambda q: _vec(0))
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        out = await semantic_search(session, "water technology", 1, limit=2)
    assert out["total"] == 3
    assert [i["issn_l"] for i in out["items"]] == ["aaaa-0001", "aaaa-0002"]
    assert out["next_cursor"] == "2"


@requires_db
async def test_total_capped_at_scan_ceiling(db_engine, seeded, monkeypatch):
    """Above the scan cap the total reads the cap and paging stops at the
    cap; the served rows stay the exact nearest."""
    from journal_browser.services import embeddings
    from journal_browser.services.search import similar

    monkeypatch.setattr(embeddings, "encode_query", lambda q: _vec(0))
    monkeypatch.setattr(similar, "SEMANTIC_TOTAL_CAP", 2)
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        page1 = await semantic_search(session, "q", 1, limit=1)
        page2 = await semantic_search(session, "q", 1, limit=1, cursor=page1["next_cursor"])
        # A cursor past the served rows: empty page, total stays the cap.
        page3 = await semantic_search(session, "q", 1, limit=1, cursor="2")
    assert page1["total"] == 2
    assert [i["issn_l"] for i in page1["items"]] == ["aaaa-0001"]
    assert [i["issn_l"] for i in page2["items"]] == ["aaaa-0002"]
    assert page2["next_cursor"] is None
    assert page3["items"] == []
    assert page3["total"] == 2


@requires_db
async def test_far_journal_out_of_total(db_engine, seeded, monkeypatch):
    """The orthogonal vector passes no distance filter: total counts only
    rows within SEMANTIC_MAX_DISTANCE."""
    from journal_browser.services import embeddings

    monkeypatch.setattr(embeddings, "encode_query", lambda q: _vec(1))
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        out = await semantic_search(session, "q", 1, limit=40)
    # bbbb-0001 matches itself (distance 0); the aaaa trio sits at
    # distance 1 (orthogonal), outside the 0.32 range.
    assert out["total"] == 1
    assert [i["issn_l"] for i in out["items"]] == ["bbbb-0001"]


@requires_db
async def test_ceil_constant_exported(db_engine, seeded):
    """The cap is a module constant wired into the scan (not silently
    unlimited); sanity-guard against regressions to the boundless count."""
    assert SEMANTIC_TOTAL_CAP >= 40
    assert SEMANTIC_TOTAL_CAP <= 10_000
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        n = len((await session.execute(select(Journal.issn_l))).all())
    assert n == 4
