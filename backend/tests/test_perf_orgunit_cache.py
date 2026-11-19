"""Orgunit detail bundle cache: the full unit page (~7 s live for a
faculty, several edge aggregates) is cached per institution + epoch +
level + name + year range + sort with the snapshot TTL. Pins: hit served
from the cache store, miss rebuilds identically, and an active year
range gets its own key."""

from conftest import requires_db
from journal_browser.models import Author
from journal_browser.services.cache import SNAPSHOT_CACHE
from journal_browser.services.orgunits import orgunit_detail


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
    await db.commit()
    return inst


@requires_db
async def test_bundle_cached_and_reused(db, institution_factory):
    inst = await _seed(db, institution_factory)
    first = await orgunit_detail(db, inst, "faculty", "Science")
    assert first is not None
    detail_keys = [k for k in SNAPSHOT_CACHE if k[0] == "unit_detail"]
    assert len(detail_keys) == 1
    second = await orgunit_detail(db, inst, "faculty", "Science")
    assert second is first  # the cached bundle object, not a rebuild


@requires_db
async def test_year_range_gets_own_key(db, institution_factory):
    inst = await _seed(db, institution_factory)
    unscoped = await orgunit_detail(db, inst, "faculty", "Science")
    scoped = await orgunit_detail(db, inst, "faculty", "Science", year_range=(2020, 2025))
    detail_keys = [k for k in SNAPSHOT_CACHE if k[0] == "unit_detail"]
    assert len(detail_keys) == 2
    assert unscoped is not scoped


@requires_db
async def test_unknown_unit_not_cached(db, institution_factory):
    inst = await _seed(db, institution_factory)
    assert await orgunit_detail(db, inst, "faculty", "Nope") is None
    assert [k for k in SNAPSHOT_CACHE if k[0] == "unit_detail"] == []
