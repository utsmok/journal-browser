"""The journals sweep reconciles issn_map against the journal universe.

Map writes are not transactional with journal creation, and upstream
issn_l re-keys can retire a target while its map rows survive (production
residue since 2026-10-22: issn 1969-0622 and 1760-7760 pointed at the
absent issn_l 1760-7760). Pruning on every full sweep converges the map;
the sweep re-adds rows for targets that come back.
"""

from sqlalchemy import select

from conftest import journal_factory
from journal_browser.harvest.openalex_journals import prune_orphan_issn_map
from journal_browser.models import IssnMap


async def test_prune_removes_only_orphan_targets(db):
    db.add(journal_factory("1234-5678"))
    db.add_all(
        [
            IssnMap(issn="1111-1111", issn_l="1234-5678", source="openalex"),
            IssnMap(issn="2222-2222", issn_l="9999-9999", source="openalex"),
        ]
    )
    await db.commit()

    assert await prune_orphan_issn_map(db) == 1
    await db.commit()

    remaining = {m.issn for m in (await db.execute(select(IssnMap))).scalars()}
    assert remaining == {"1111-1111"}


async def test_prune_is_idempotent(db):
    db.add(journal_factory("1234-5678"))
    db.add(IssnMap(issn="1111-1111", issn_l="1234-5678", source="openalex"))
    await db.commit()

    assert await prune_orphan_issn_map(db) == 0
    assert len((await db.execute(select(IssnMap))).scalars().all()) == 1
