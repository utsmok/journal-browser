"""Data window semantics: NULL end = open; bounded end filters strictly."""

from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import journal_factory, requires_db
from journal_browser.models import Institution


def test_window_years_open_end_runs_to_current_year():
    inst = Institution(code="ut", name="UT", data_window_start=2024, data_window_end=None)
    assert inst.window_years == [2024, 2025, 2026]


def test_window_years_bounded_end_is_inclusive():
    inst = Institution(code="ut", name="UT", data_window_start=2024, data_window_end=2025)
    assert inst.window_years == [2024, 2025]


async def _seed_works(db, inst, run, rows):
    from journal_browser.models import Work

    db.add_all(
        [
            Work(
                institution_id=inst.id,
                pure_uuid=f"{inst.code}-{i}",
                title=title,
                norm_title=title.lower(),
                year=year,
                work_type=work_type,
                doi_normalized=doi,
                journal_issn_l="0000-0000",
                first_seen_run=run.id,
                last_seen_run=run.id,
            )
            for i, (title, year, work_type, doi) in enumerate(rows)
        ]
    )


@requires_db
async def test_windowed_service_query_filters_bounded_end(db):
    """The services' year_end fill (9999 for an open end) keeps later rows;
    a bounded end excludes years past it. Exercises the works-table query
    behind the detail-enrichment endpoints."""
    from journal_browser.models import HarvestRun
    from journal_browser.services.detail_enrichment import list_works

    inst_open = Institution(code="open", name="Open", data_window_end=None)
    inst_bounded = Institution(code="bounded", name="B", data_window_end=2023)
    db.add_all([inst_open, inst_bounded, journal_factory("0000-0000")])
    await db.flush()
    run = HarvestRun(
        source="pure",
        entity_type="work",
        status="completed",
        institution_id=inst_open.id,
        config_fingerprint="t",
    )
    db.add(run)
    await db.flush()
    await _seed_works(
        db,
        inst_open,
        run,
        [("In window", 2023, "article", None), ("Far future", 2030, "article", None)],
    )
    await _seed_works(
        db,
        inst_bounded,
        run,
        [("In window", 2023, "article", None), ("Far future", 2030, "article", None)],
    )
    await db.commit()

    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    async with maker() as session:
        for inst, expect_years in ((inst_open, {2023, 2030}), (inst_bounded, {2023})):
            page = await list_works(session, "0000-0000", inst, page=1, page_size=50)
            got = {i["year"] for i in page["items"]}
            assert got == expect_years, f"{inst.code}: {got}"


@requires_db
async def test_works_tab_total_matches_stats_count(db):
    """Regression (LNCS 1112 vs 1018, reported 2026-11-08): the tab used to
    build its list from store rows gated by affiliated DOIs, so DOI-less
    Pure works dropped from the list while store-side never-journal-output
    types slipped in — card and tab disagreed. The tab now serves the
    stats population: total equals journal_flags.works_count, DOI-less
    works list (marked Pure-only), excluded types and store-only rows do
    not, and page rows carry their Pure authors and research groups."""
    from journal_browser.harvest.denorm import refresh_institution_stats
    from journal_browser.harvest.institution_stats import write_pure_canon_stats
    from journal_browser.models import (
        Author,
        HarvestRun,
        JournalFlags,
        OpenalexWork,
        WorkPureAuthor,
    )
    from journal_browser.services.detail_enrichment import list_works

    inst = Institution(code="ut", name="UT", data_window_start=2020, data_window_end=None)
    db.add_all([inst, journal_factory("0000-0000")])
    await db.flush()
    run = HarvestRun(
        source="pure",
        entity_type="work",
        status="completed",
        institution_id=inst.id,
        config_fingerprint="t",
    )
    db.add(run)
    await db.flush()
    await _seed_works(
        db,
        inst,
        run,
        [
            ("Doi Work", 2021, "article", "10.1/one"),
            ("No Doi Work", 2020, "article", None),
            ("A Book Part", 2021, "info:eu-repo/semantics/bookPart", "10.2/part"),
        ],
    )
    db.add_all(
        [
            # Store enrichment for the DOI'd work.
            OpenalexWork(
                institution_id=inst.id,
                w_id="W1",
                doi_normalized="10.1/one",
                title="Doi Work",
                year=2021,
                work_type="article",
                venue_issn_l="0000-0000",
                oa_status="gold",
                fwci=1.5,
                cited_by_count=5,
                is_retracted=True,
            ),
            # Store-only row: in OpenAlex's venue but not in Pure — never ours.
            OpenalexWork(
                institution_id=inst.id,
                w_id="W9",
                doi_normalized="10.9/store-only",
                title="Store Only",
                year=2021,
                work_type="article",
                venue_issn_l="0000-0000",
                cited_by_count=99,
            ),
        ]
    )
    alice = Author(
        institution_id=inst.id,
        pure_uuid="a1",
        name="Alice Alpha",
        research_group="Group X",
        confirmed=True,
        n_works=1,
    )
    bob = Author(
        institution_id=inst.id,
        pure_uuid="a2",
        name="Bob Beta",
        confirmed=True,
        n_works=1,
    )
    db.add_all([alice, bob])
    await db.flush()
    db.add_all(
        [
            WorkPureAuthor(
                institution_id=inst.id,
                work_pure_uuid=f"{inst.code}-0",
                person_uuid="a1",
                position=0,
            ),
            WorkPureAuthor(
                institution_id=inst.id,
                work_pure_uuid=f"{inst.code}-1",
                person_uuid="a2",
                position=0,
            ),
        ]
    )
    await db.commit()

    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    async with maker() as session:
        # The stats path (what the search card shows) over the same corpus.
        await write_pure_canon_stats(session, inst)
        await refresh_institution_stats(session, inst)
        flags = await session.get(JournalFlags, {"institution_id": inst.id, "issn_l": "0000-0000"})
        page = await list_works(session, "0000-0000", inst, page=1, page_size=50)

    assert flags is not None and flags.works_count == 2
    assert page["total"] == 2
    assert [i["title"] for i in page["items"]] == ["Doi Work", "No Doi Work"]
    doi_item, nodoi_item = page["items"]
    assert doi_item["in_openalex"] is True
    assert doi_item["id"] == "W1"
    assert doi_item["fwci"] == 1.5
    assert doi_item["is_retracted"] is True
    assert doi_item["ut_authors"] == [{"id": "a1", "name": "Alice Alpha"}]
    assert doi_item["ut_groups"] == [{"name": "Group X"}]
    assert nodoi_item["in_openalex"] is False
    assert nodoi_item["id"] is None
    assert nodoi_item["ut_authors"] == [{"id": "a2", "name": "Bob Beta"}]
    assert nodoi_item["ut_groups"] == []
