"""OpenAlex page-level bulk upsert (the 1.25M-row sweep path)."""

from sqlalchemy import select

from conftest import requires_db
from journal_browser.harvest.openalex_journals import _upsert_journal_page
from journal_browser.models import IssnMap, Journal


@requires_db
async def test_page_upsert_last_wins_and_maps_issns(db):
    n = await _upsert_journal_page(
        db,
        [
            {"id": "S1", "issn_l": "0043-1354", "display_name": "First"},
            {"id": "S2", "issn_l": "0043-1354", "display_name": "Second", "issn": ["1234-5679"]},
        ],
    )
    await db.flush()
    assert n == 2  # both payloads normalized, one journal row
    row = await db.get(Journal, "0043-1354")
    assert row.title == "Second"
    assert row.openalex_id == "S2"
    assert row.search_text == "Second"
    variants = {
        m.issn: m.issn_l
        for m in (await db.execute(select(IssnMap).where(IssnMap.issn_l == "0043-1354"))).scalars()
    }
    assert variants == {"0043-1354": "0043-1354", "1234-5679": "0043-1354"}


@requires_db
async def test_page_upsert_conflict_updates_existing(db):
    await _upsert_journal_page(db, [{"id": "S1", "issn_l": "0043-1354", "display_name": "Old"}])
    await db.flush()
    await _upsert_journal_page(db, [{"id": "S1", "issn_l": "0043-1354", "display_name": "New"}])
    await db.flush()
    row = await db.get(Journal, "0043-1354")
    assert row.title == "New"
    assert row.search_text == "New"


@requires_db
async def test_seed_deal_journals_lands_raw_payloads(db):
    """Regression: the seed route stores verbatim source payloads in
    source_records, same as the sweep route."""
    from types import SimpleNamespace

    from journal_browser.harvest.openalex_journals import seed_deal_journals
    from journal_browser.models import Deal, DealJournal, HarvestRun, SourceRecord

    payload = {
        "id": "https://openalex.org/S1",
        "issn_l": "0043-1354",
        "display_name": "Seed J",
        "apc_prices": [{"currency": "EUR", "price": 2500}],
    }

    class FakeSources:
        async def batch_get(self, issns, field=None):
            return {issns[0]: dict(payload)}

    deal = Deal(status="current")
    db.add(deal)
    await db.flush()
    db.add(DealJournal(deal_id=deal.id, issn="0043-1354", source="jct"))
    await db.flush()

    stats = await seed_deal_journals(SimpleNamespace(sources=FakeSources()), db)
    assert stats["sources_found"] == 1
    row = await db.get(Journal, "0043-1354")
    assert row.title == "Seed J"
    assert row.apc_prices == [{"currency": "EUR", "price": 2500}]
    raw = (
        await db.execute(
            select(SourceRecord).where(
                SourceRecord.source == "openalex",
                SourceRecord.entity_type == "sources",
                SourceRecord.source_pk == payload["id"],
            )
        )
    ).scalar_one()
    assert raw.payload["apc_prices"] == [{"currency": "EUR", "price": 2500}]
    run = await db.get(HarvestRun, raw.harvest_run_id)
    assert run.status == "completed" and run.stats["records_stored"] == 1
