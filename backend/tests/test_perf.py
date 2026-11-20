"""Stale-while-revalidate detail bundles: a harvest epoch bump must not
turn every unit/publisher page into a multi-second cold rebuild. The
previous epoch's bundle is served immediately while a background task
rebuilds on a fresh session (services/cache.py SWR helpers)."""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from conftest import requires_db
from journal_browser.models import Author, CacheEpoch
from journal_browser.services.cache import SWR_CACHE, swr_get, swr_put, swr_schedule
from journal_browser.services.orgunits import orgunit_detail


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
    assert done and store[("k",)] == ("e2", {"b": 2})
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
    key = ("unit_detail", inst.id, "faculty", "Science", None, "share")
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
