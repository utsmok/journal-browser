"""derive_oa_colors_local: modal non-green color from locally held works."""

from conftest import requires_db
from journal_browser.harvest.journal_oa import derive_oa_colors_local
from journal_browser.models import Journal, Work


async def _journal(db, issn_l: str, observed: str | None = None) -> Journal:
    journal = Journal(issn_l=issn_l, title="t", oa_status_observed=observed)
    db.add(journal)
    await db.flush()
    return journal


_work_seq = {"n": 0}


async def _work(db, inst, run_id: int, issn: str | None, status: str | None) -> None:
    _work_seq["n"] += 1
    n = _work_seq["n"]
    db.add(
        Work(
            institution_id=inst.id,
            pure_uuid=f"uuid-{n}",
            doi_normalized=f"10.1234/w{n}",
            title="t",
            norm_title="t",
            year=2020,
            first_seen_run=run_id,
            last_seen_run=run_id,
            journal_issn_l=issn,
            oa_status=status,
        )
    )


@requires_db
async def test_derive_oa_colors_modal_and_nulls_only(db, institution_factory):
    inst = await institution_factory()
    from journal_browser.models import HarvestRun

    run = HarvestRun(source="test", entity_type="works", config_fingerprint="t")
    db.add(run)
    await db.flush()

    gold = await _journal(db, "1111-1111")
    green_only = await _journal(db, "2222-2222")
    already = await _journal(db, "3333-3333", observed="bronze")
    no_status = await _journal(db, "4444-4444")

    for _ in range(3):
        await _work(db, inst, run.id, gold.issn_l, "gold")
    await _work(db, inst, run.id, gold.issn_l, "green")
    await _work(db, inst, run.id, green_only.issn_l, "green")
    await _work(db, inst, run.id, already.issn_l, "gold")
    await _work(db, inst, run.id, no_status.issn_l, None)
    await _work(db, inst, run.id, None, "gold")
    await db.commit()

    stats = await derive_oa_colors_local(db)
    await db.commit()

    assert stats["colored"] == 2
    await db.refresh(gold)
    await db.refresh(green_only)
    await db.refresh(already)
    await db.refresh(no_status)
    assert gold.oa_status_observed == "gold"
    # All-green evidence stores 'green' (= venue color unknown).
    assert green_only.oa_status_observed == "green"
    # Existing colors are never overwritten.
    assert already.oa_status_observed == "bronze"
    # Works without a status or without a journal contribute nothing.
    assert no_status.oa_status_observed is None

    # Rerun is a no-op: everything colored already, NULLs stay untouched.
    stats2 = await derive_oa_colors_local(db)
    assert stats2["colored"] == 0
