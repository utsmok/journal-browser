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
