"""Data window semantics: NULL end = open; bounded end filters strictly."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import journal_factory, requires_db
from journal_browser.config import Settings
from journal_browser.models import Institution


def test_settings_window_end_zero_means_open():
    """JB_DATA_WINDOW_END=0 is the compose/.env open-ended default, not year 0."""
    for raw in (0, "0", ""):
        s = Settings(data_window_end=raw, data_window_start=2020)
        assert s.data_window_end is None
        assert s.window_years
    assert Settings(data_window_end=2025, data_window_start=2020).data_window_end == 2025


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

    assert flags is not None and flags.works_count == 3
    assert page["total"] == 3
    # sort_work_items: year desc, cited desc, title asc — the book part
    # (book parts are app output since the 2026-11 type review) outranks
    # the uncited 2020 work
    assert [i["title"] for i in page["items"]] == ["Doi Work", "A Book Part", "No Doi Work"]
    doi_item, nodoi_item = page["items"][0], page["items"][2]
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


PASSWORD = "test-admin-pw"


@pytest.fixture
async def admin_api(client, monkeypatch, tmp_path):
    monkeypatch.setenv("JB_ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setenv("JB_SETTINGS_YAML", str(tmp_path / "settings.yaml"))
    from journal_browser.config import reset_settings_cache

    reset_settings_cache()
    yield client
    reset_settings_cache()


async def _admin_headers(client) -> dict[str, str]:
    r = await client.post("/api/v1/admin/login", json={"password": PASSWORD})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def _seed_ut_journal(db, window_start: int):
    """Institution 'ut' + journal 0000-0000 + a completed pure run."""
    from journal_browser.models import HarvestRun

    inst = Institution(code="ut", name="UT", data_window_start=window_start, data_window_end=None)
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
    return inst, run


@requires_db
async def test_card_count_ignores_openalex_only_year(db):
    """Regression (card half of LNCS 1112 vs 1018): works_count summed the
    openalex_institution_filter rows of years the canon pass has no row for,
    inflating the card over the tab. Only pure_canon rows contribute, so an
    OpenAlex-only year changes nothing."""
    from sqlalchemy import select

    from journal_browser.harvest.denorm import refresh_institution_stats
    from journal_browser.harvest.institution_stats import write_pure_canon_stats
    from journal_browser.models import InstitutionWorksStats, JournalFlags
    from journal_browser.services.detail_enrichment import list_works

    inst, run = await _seed_ut_journal(db, window_start=2020)
    await _seed_works(
        db, inst, run, [("One", 2021, "article", None), ("Two", 2022, "article", None)]
    )
    db.add(
        InstitutionWorksStats(
            institution_id=inst.id,
            source="openalex_institution_filter",
            issn_l="0000-0000",
            year=2019,
            works_count=1112,
        )
    )
    await db.commit()

    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    async with maker() as session:
        await write_pure_canon_stats(session, inst)
        await refresh_institution_stats(session, inst)
        inst = (
            await session.execute(select(Institution).where(Institution.code == "ut"))
        ).scalar_one()
        flags = await session.get(JournalFlags, {"institution_id": inst.id, "issn_l": "0000-0000"})
        page = await list_works(session, "0000-0000", inst, page=1, page_size=50)

    assert flags is not None and flags.works_count == 2
    assert page["total"] == 2


@requires_db
async def test_full_pure_sweep_refreshes_card_count(db, monkeypatch):
    """A full sweep retires works; the job rebuilds the canon stats rows and
    flags in the same run, so the card matches the tab without a separate
    stats job."""
    from datetime import UTC, datetime

    from jobs import harvest_pure as jobs_harvest_pure
    from sqlalchemy import select

    from journal_browser.harvest.denorm import refresh_institution_stats
    from journal_browser.harvest.institution_stats import write_pure_canon_stats
    from journal_browser.models import JournalFlags, Work

    inst, run = await _seed_ut_journal(db, window_start=2020)
    await _seed_works(
        db, inst, run, [("One", 2021, "article", None), ("Two", 2022, "article", None)]
    )
    await write_pure_canon_stats(db, inst)
    await refresh_institution_stats(db, inst)
    await db.commit()

    async def fake_sweep(session, institution, years, *, limit=None, full_sweep=False):
        work = (
            await session.execute(select(Work).where(Work.pure_uuid == f"{institution.code}-0"))
        ).scalar_one()
        work.retired_at = datetime.now(UTC)
        await session.flush()
        return {"sets": {}, "retired": 1, "records_stored": 0}

    monkeypatch.setattr(jobs_harvest_pure, "harvest_pure_years", fake_sweep)
    stats = await jobs_harvest_pure.main(db, inst, None, full_sweep=True)

    assert stats["pure_canon_rows"] == 1
    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    async with maker() as session:
        flags = await session.get(JournalFlags, {"institution_id": inst.id, "issn_l": "0000-0000"})
    assert flags is not None and flags.works_count == 1


@requires_db
async def test_partial_pure_run_leaves_stats_to_the_stats_job(db, monkeypatch):
    """A --years run neither retires nor re-baselines, so it must not touch
    stats or flags: the card keeps the last stats job's numbers."""
    from jobs import harvest_pure as jobs_harvest_pure

    from journal_browser.harvest.denorm import refresh_institution_stats
    from journal_browser.harvest.institution_stats import write_pure_canon_stats
    from journal_browser.models import JournalFlags, Work

    inst, run = await _seed_ut_journal(db, window_start=2020)
    await _seed_works(
        db, inst, run, [("One", 2021, "article", None), ("Two", 2022, "article", None)]
    )
    await write_pure_canon_stats(db, inst)
    await refresh_institution_stats(db, inst)
    await db.commit()

    async def fake_run(session, institution, years, *, limit=None, full_sweep=False):
        session.add(
            Work(
                institution_id=inst.id,
                pure_uuid="ut-new",
                title="New",
                norm_title="new",
                year=2021,
                work_type="article",
                journal_issn_l="0000-0000",
                first_seen_run=run.id,
                last_seen_run=run.id,
            )
        )
        await session.flush()
        return {"sets": {}, "records_stored": 1}

    monkeypatch.setattr(jobs_harvest_pure, "harvest_pure_years", fake_run)
    stats = await jobs_harvest_pure.main(db, inst, None, years=[2021])

    assert "pure_canon_rows" not in stats
    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    async with maker() as session:
        flags = await session.get(JournalFlags, {"institution_id": inst.id, "issn_l": "0000-0000"})
    assert flags is not None and flags.works_count == 2


@requires_db
async def test_admin_window_edit_updates_card_count_immediately(admin_api, db):
    """Regression (2026-11-08): the window PUT committed without touching
    stats or flags, leaving the card on the old window until the nightly
    stats job. The same request now rebuilds them, so card and tab agree."""
    from sqlalchemy import select

    from journal_browser.harvest.denorm import refresh_institution_stats
    from journal_browser.harvest.institution_stats import write_pure_canon_stats
    from journal_browser.models import JournalFlags
    from journal_browser.services.detail_enrichment import list_works

    inst, run = await _seed_ut_journal(db, window_start=2021)
    await _seed_works(
        db, inst, run, [("Pre window", 2020, "article", None), ("In window", 2021, "article", None)]
    )
    await write_pure_canon_stats(db, inst)
    await refresh_institution_stats(db, inst)
    await db.commit()

    headers = await _admin_headers(admin_api)
    r = await admin_api.put(
        "/api/v1/admin/institutions/ut", headers=headers, json={"data_window_start": 2020}
    )
    assert r.status_code == 200

    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    async with maker() as session:
        inst = (
            await session.execute(select(Institution).where(Institution.code == "ut"))
        ).scalar_one()
        flags = await session.get(JournalFlags, {"institution_id": inst.id, "issn_l": "0000-0000"})
        page = await list_works(session, "0000-0000", inst, page=1, page_size=50)

    assert flags is not None and flags.works_count == 2
    assert page["total"] == 2
