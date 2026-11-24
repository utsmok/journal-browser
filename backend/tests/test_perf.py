"""Stale-while-revalidate detail bundles: a harvest epoch bump must not
turn every unit/publisher page into a multi-second cold rebuild. The
previous epoch's bundle is served immediately while a background task
rebuilds on a fresh session (services/cache.py SWR helpers)."""

import asyncio
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import delete, select

from conftest import journal_factory, requires_db
from journal_browser.config import reset_settings_cache
from journal_browser.models import (
    Author,
    CacheEpoch,
    HarvestRun,
    Journal,
    JournalFlags,
    OpenalexWork,
    Work,
)
from journal_browser.services.cache import (
    SNAPSHOT_CACHE,
    SNAPSHOT_TTL,
    SWR_CACHE,
    cache_get,
    cache_put,
    swr_get,
    swr_put,
    swr_schedule,
)
from journal_browser.services.orgunits import orgunit_detail, search_orgunits


async def test_swr_get_put_and_schedule():
    store: dict = {}
    assert swr_get(store, ("k",), "e1") == (False, None)
    swr_put(store, ("k",), "e1", {"b": 1})
    assert swr_get(store, ("k",), "e1") == (True, {"b": 1})
    # stale epoch: bundle served, fresh=False
    fresh, bundle = swr_get(store, ("k",), "e2")
    assert (fresh, bundle) == (False, {"b": 1})

    # schedule runs the factory and stores the new epoch's bundle
    done = {}

    async def factory():
        done["ran"] = True
        return "e2", {"b": 2}

    assert swr_schedule(store, ("k",), factory) is True
    # second schedule while in flight is a no-op
    assert swr_schedule(store, ("k",), factory) is False
    for _ in range(100):
        if done:
            break
        await asyncio.sleep(0.01)
    assert done and store[("k",)][:2] == ("e2", {"b": 2})
    assert swr_get(store, ("k",), "e2") == (True, {"b": 2})


async def _seed(db, institution_factory):
    inst = await institution_factory(code="ut")
    db.add(
        Author(
            institution_id=inst.id,
            pure_uuid="a1",
            name="Ann A",
            faculty="Science",
            research_group="Group X",
            confirmed=True,
        )
    )
    if await db.scalar(select(CacheEpoch.id).where(CacheEpoch.id == 1)) is None:
        db.add(CacheEpoch(id=1))
    await db.commit()
    return inst


@requires_db
async def test_orgunit_bundle_stale_served_on_epoch_bump(db, institution_factory):
    inst = await _seed(db, institution_factory)
    SWR_CACHE.clear()
    key = ("unit_detail", inst.id, "faculty", "Science", None, "share", True)
    first = await orgunit_detail(db, inst, "faculty", "Science")
    assert first is not None
    fresh, cached = swr_get(SWR_CACHE, key, (await db.scalar(select(CacheEpoch.bumped_at))))
    assert fresh and cached is first

    # epoch bump (as a harvest wave does): the previous epoch's bundle is
    # served instantly and a background rebuild is scheduled.
    row = (await db.scalars(select(CacheEpoch))).one()
    row.bumped_at = datetime.now(UTC) + timedelta(seconds=1)
    await db.commit()
    second = await orgunit_detail(db, inst, "faculty", "Science")
    assert second is cached  # stale bundle, no rebuild in the request path
    # give the scheduled rebuild (fresh session on the test engine) a slot
    for _ in range(200):
        await asyncio.sleep(0.01)
        fresh, rebuilt = swr_get(SWR_CACHE, key, await db.scalar(select(CacheEpoch.bumped_at)))
        if fresh:
            break
    assert fresh and isinstance(rebuilt, dict)


async def test_swr_put_evicts_oldest_when_full():
    store: dict = {}
    for i in range(5):
        swr_put(store, ("k", i), "e1", i, max_entries=3)
    assert list(store) == [("k", 2), ("k", 3), ("k", 4)]
    # Hit promotes key 2 ahead of key 3.
    assert swr_get(store, ("k", 2), "e1") == (True, 2)
    swr_put(store, ("k", 5), "e1", 5, max_entries=3)
    assert ("k", 3) not in store and ("k", 2) in store


async def test_none_bundle_is_never_cached():
    """A rebuild that finds the entity gone answers (epoch, None). None
    must not become a fresh bundle, and it retires the stale one, so the
    next request builds inline and answers 404."""
    store: dict = {}
    swr_put(store, ("k",), "e2", None)
    assert store == {}
    swr_put(store, ("k",), "e1", {"b": 1})
    swr_put(store, ("k",), "e2", None)
    assert swr_get(store, ("k",), "e2") == (False, None)

    swr_put(store, ("k",), "e1", {"b": 1})

    async def vanished():
        return "e2", None

    assert swr_schedule(store, ("k",), vanished) is True
    for _ in range(100):
        if not store:
            break
        await asyncio.sleep(0.01)
    assert store == {}


async def test_byte_cap_evicts_least_recently_used(monkeypatch, tmp_path):
    """The store also drops entries by size: past JB_CACHE_MAX_MB the least
    recently used go first, and an entry larger than the cap stays alone."""
    monkeypatch.setenv("JB_SETTINGS_YAML", str(tmp_path / "missing.yaml"))
    monkeypatch.setenv("JB_CACHE_MAX_MB", "1")
    reset_settings_cache()

    class Bundle(BaseModel):
        text: str

    try:
        store: dict = {}
        cache_put(store, ("a",), Bundle(text="a" * 400_000))
        cache_put(store, ("b",), Bundle(text="b" * 400_000))
        cache_get(store, ("a",), SNAPSHOT_TTL)
        cache_put(store, ("c",), Bundle(text="c" * 400_000))
        assert list(store) == [("a",), ("c",)]
        cache_put(store, ("d",), Bundle(text="d" * 2_000_000))
        assert list(store) == [("d",)]
        assert cache_get(store, ("d",), SNAPSHOT_TTL) == Bundle(text="d" * 2_000_000)
    finally:
        reset_settings_cache()


@requires_db
async def test_deleted_journal_404s_once_the_stale_rebuild_ran(client, db, institution_factory):
    """End to end: a harvest deletes a cached journal and bumps the epoch.
    The stale bundle is served once, and the request after the background
    rebuild finds nothing answers 404, not a cached None."""
    await _seed(db, institution_factory)
    db.add(journal_factory("1234-5678"))
    await db.commit()
    url = "/api/v1/ut/journals/1234-5678?include_gaps=false"
    assert (await client.get(url)).status_code == 200

    await db.execute(delete(Journal).where(Journal.issn_l == "1234-5678"))
    row = (await db.scalars(select(CacheEpoch))).one()
    row.bumped_at = datetime.now(UTC) + timedelta(seconds=1)
    await db.commit()
    assert (await client.get(url)).status_code == 200
    for _ in range(200):
        await asyncio.sleep(0.01)
        if not any(k[0] == "journal_detail" for k in SWR_CACHE):
            break
    assert (await client.get(url)).status_code == 404


@requires_db
async def test_lazy_cris_gaps_and_scoped_unit_cache(client, db, institution_factory):
    inst = await _seed(db, institution_factory)
    j = journal_factory(
        issn_l="1111-2222",
        title="Gap Test Journal",
        publisher_name="Gap Press",
        publisher_canonical="Gap Press",
        type="journal",
    )
    db.add(j)
    run = HarvestRun(
        source="pure", entity_type="works", status="completed", config_fingerprint="test"
    )
    db.add(run)
    await db.flush()
    db.add(JournalFlags(institution_id=inst.id, issn_l=j.issn_l, works_window_plus=10))
    db.add(
        Work(
            institution_id=inst.id,
            pure_uuid="w-1",
            title="Registered Pure Work",
            norm_title="registered pure work",
            year=2024,
            work_type="article",
            journal_issn_l=j.issn_l,
            first_seen_run=run.id,
            last_seen_run=run.id,
        )
    )
    db.add(
        OpenalexWork(
            institution_id=inst.id,
            w_id="W100",
            doi_normalized="10.1234/gap-standalone",
            title="Missing Standalone",
            year=2024,
            work_type="article",
            venue_issn_l=j.issn_l,
            venue_name="Gap Test Journal",
            source="works_stats",
            is_part=False,
            parent_works=[],
        )
    )
    db.add(
        OpenalexWork(
            institution_id=inst.id,
            w_id="W101",
            doi_normalized="10.1234/gap-chapter",
            title="Missing Chapter",
            year=2024,
            work_type="book-chapter",
            venue_issn_l=j.issn_l,
            venue_name="Gap Test Journal",
            source="works_stats",
            is_part=True,
            parent_works=[{"id": "W999", "name": "Missing Book", "rel": "volume"}],
        )
    )
    await db.commit()

    # include_gaps=false skips heavy gap fetch while returning exact counts & parts_counts.
    fast_j = (
        await client.get(f"/api/v1/{inst.code}/journals/{j.issn_l}?include_gaps=false")
    ).json()
    assert fast_j["openalex_only"]["available"] is True
    assert fast_j["openalex_only"]["items"] == []
    assert fast_j["openalex_only"]["total"] == 2
    assert fast_j["openalex_only"]["parts_counts"] == {
        "all": 2,
        "standalone": 1,
        "chapter": 1,
        "part": 0,
    }

    fast_p = (
        await client.get(f"/api/v1/{inst.code}/publishers/Gap%20Press?include_gaps=false")
    ).json()
    assert fast_p["openalex_only"]["available"] is True
    assert fast_p["openalex_only"]["items"] == []
    assert fast_p["openalex_only"]["total"] == 2
    assert fast_p["openalex_only"]["parts_counts"]["all"] == 2

    fast_u = (
        await client.get(f"/api/v1/{inst.code}/orgunits/faculty/Science?include_gaps=false")
    ).json()
    assert fast_u["openalex_only"]["available"] is True
    assert fast_u["openalex_only"]["items"] == []
    assert fast_u["openalex_only"]["total"] == 0

    # Lazy /cris-gaps endpoint returns parts_counts + unfiltered chapter_rollup even when filtered.
    gaps_standalone = (
        await client.get(f"/api/v1/{inst.code}/publishers/Gap%20Press/cris-gaps?parts=standalone")
    ).json()
    assert gaps_standalone["openalex_only"]["total"] == 1
    assert gaps_standalone["openalex_only"]["parts_counts"] == {
        "all": 2,
        "standalone": 1,
        "chapter": 1,
        "part": 0,
    }
    assert gaps_standalone["chapter_rollup"]["chapters_total"] == 1

    gaps_journal = (await client.get(f"/api/v1/{inst.code}/journals/{j.issn_l}/cris-gaps")).json()
    assert gaps_journal["openalex_only"]["total"] == 2
    assert gaps_journal["chapter_rollup"]["chapters_total"] == 1

    # Year-scoped orgunit search populates SNAPSHOT_CACHE under scoped_units.
    SNAPSHOT_CACHE.clear()
    await search_orgunits(db, institution=inst, level="faculty", year_range=(2022, 2024))
    assert any(k[0] == "scoped_units" for k in SNAPSHOT_CACHE)
