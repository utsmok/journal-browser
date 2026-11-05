"""Data window semantics: NULL end = open; bounded end filters strictly."""

from sqlalchemy.ext.asyncio import async_sessionmaker

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
    a bounded end excludes years past it. Exercises the store-query idiom
    shared by the detail-enrichment endpoints."""
    from journal_browser.models import OpenalexWork
    from journal_browser.services.detail_enrichment import list_works

    inst_open = Institution(code="open", name="Open", data_window_end=None)
    inst_bounded = Institution(code="bounded", name="B", data_window_end=2023)
    db.add_all([inst_open, inst_bounded])
    await db.flush()

    for inst in (inst_open, inst_bounded):
        db.add_all(
            [
                OpenalexWork(
                    institution_id=inst.id,
                    w_id=f"{inst.code}-2023",
                    title="In window",
                    year=2023,
                    venue_issn_l="0000-0000",
                    cited_by_count=1,
                ),
                OpenalexWork(
                    institution_id=inst.id,
                    w_id=f"{inst.code}-2030",
                    title="Far future",
                    year=2030,
                    venue_issn_l="0000-0000",
                    cited_by_count=2,
                ),
            ]
        )
    await db.commit()

    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    async with maker() as session:
        for inst, expect_years in ((inst_open, {2023, 2030}), (inst_bounded, {2023})):
            page = await list_works(session, "0000-0000", inst, page=1, page_size=50)
            got = {i["year"] for i in page["items"]}
            assert got == expect_years, f"{inst.code}: {got}"
