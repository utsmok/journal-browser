"""Facet cache rewrite: filtered facet keys are cached too (short TTL,
harvest epoch in the key), so a filter click no longer rebuilds the
~1.5 s aggregate pass. Pins: filtered results equal a rebuild, filtered
keys are stored and reused, different filter sets map to different keys,
and the default landing view keeps its long-TTL key shape."""

import pytest

from conftest import journal_factory, requires_db
from journal_browser.models import JournalFlags
from journal_browser.services.cache import FACET_CACHE
from journal_browser.services.search.facets import facet_counts


async def _seed(db, institution_factory):
    inst = await institution_factory(code="ut")
    rows = []
    for n, (issn, quartile, in_doaj) in enumerate(
        [("aaaa-0001", "Q1", True), ("aaaa-0002", "Q1", False), ("bbbb-0001", "Q2", False)]
    ):
        db.add(
            journal_factory(
                issn,
                title=f"J {n}",
                search_text=f"J {n}",
                latest_quartile=quartile,
                is_in_doaj=in_doaj,
            )
        )
        rows.append(JournalFlags(institution_id=inst.id, issn_l=issn, works_count=10,
                                 works_window_plus=10))
    db.add_all(rows)
    await db.commit()
    return inst.id


@requires_db
async def test_filtered_result_matches_rebuild(db, institution_factory):
    inst_id = await _seed(db, institution_factory)
    fresh = await facet_counts(db, institution_id=inst_id, q="", quartile="Q1")
    FACET_CACHE.clear()
    rebuilt = await facet_counts(db, institution_id=inst_id, q="", quartile="Q1")
    assert fresh == rebuilt
    assert fresh[1] == 2


@requires_db
async def test_filtered_key_cached_and_reused(db, institution_factory):
    inst_id = await _seed(db, institution_factory)
    first = await facet_counts(db, institution_id=inst_id, q="", quartile="Q1")
    puts = len(FACET_CACHE)
    second = await facet_counts(db, institution_id=inst_id, q="", quartile="Q1")
    assert second == first
    assert len(FACET_CACHE) == puts  # served from cache, nothing re-stored


@requires_db
async def test_distinct_filters_distinct_keys(db, institution_factory):
    inst_id = await _seed(db, institution_factory)
    q1 = await facet_counts(db, institution_id=inst_id, q="", quartile="Q1")
    q2 = await facet_counts(db, institution_id=inst_id, q="", quartile="Q2")
    assert q1[1] == 2
    assert q2[1] == 1
    assert q1 != q2
    assert len(FACET_CACHE) >= 2


@requires_db
async def test_default_view_key_uncollided_by_filters(db, institution_factory):
    """The landing-view key (sig None) is distinct from every filtered key,
    so cached landing facets can never leak into a filtered request."""
    inst_id = await _seed(db, institution_factory)
    landing = await facet_counts(db, institution_id=inst_id, q="")
    filtered = await facet_counts(db, institution_id=inst_id, q="", quartile="Q1")
    assert landing[1] == 3
    assert filtered[1] == 2
    default_keys = [k for k in FACET_CACHE if k[0] == "facets" and k[-1] is None]
    assert len(default_keys) == 1
