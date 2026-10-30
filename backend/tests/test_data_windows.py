"""Data window semantics: NULL end = open; bounded end filters strictly."""

import pytest

from conftest import requires_db
from journal_browser.models import Institution


def test_window_years_open_end_runs_to_current_year():
    inst = Institution(code="ut", name="UT", data_window_start=2024, data_window_end=None)
    assert inst.window_years == [2024, 2025, 2026]


def test_window_years_bounded_end_is_inclusive():
    inst = Institution(code="ut", name="UT", data_window_start=2024, data_window_end=2025)
    assert inst.window_years == [2024, 2025]


@requires_db
async def test_windowed_service_query_filters_bounded_end(db):
    """The services' year_end fill (9999 for an open end) keeps later rows;
    a bounded end excludes years past it. Exercises the _journal_works idiom
    shared by the detail-enrichment endpoints."""
    from datetime import UTC, datetime

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from journal_browser.models import HarvestRun, SourceRecord
    from journal_browser.services.detail_enrichment import _journal_works

    inst_open = Institution(code="open", name="Open", data_window_end=None)
    inst_bounded = Institution(code="bounded", name="B", data_window_end=2023)
    db.add_all([inst_open, inst_bounded])
    await db.flush()

    now = datetime.now(UTC)
    for inst in (inst_open, inst_bounded):
        run = HarvestRun(
            source="openalex",
            entity_type="works_stats",
            institution_id=inst.id,
            config_fingerprint="test",
        )
        db.add(run)
        await db.flush()
        for year in (2023, 2030):
            db.add(
                SourceRecord(
                    source="openalex",
                    entity_type="works_stats",
                    source_pk=f"{inst.code}-{year}",
                    harvest_run_id=run.id,
                    content_hash=f"h-{inst.code}-{year}",
                    harvested_at=now,
                    payload={
                        "publication_year": year,
                        "primary_location": {"source": {"issn_l": "0000-0000"}},
                    },
                )
            )
    await db.commit()

    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    async with maker() as session:
        for inst, expect_years in ((inst_open, {2023, 2030}), (inst_bounded, {2023})):
            year_end = inst.data_window_end if inst.data_window_end is not None else 9999
            rows = _journal_works("0000-0000", inst.id, inst.data_window_start, year_end)
            payloads = (await session.execute(select(rows.c.payload))).scalars().all()
            got = {p["publication_year"] for p in payloads}
            assert got == expect_years, f"{inst.code}: {got}"
