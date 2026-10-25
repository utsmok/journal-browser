"""Regression tests for the 2026-10-25 backend audit fixes."""

import asyncio
import importlib.util
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from journal_browser.harvest.openapc import build_aggregates
from journal_browser.harvest.pure import _consume_oai_pages, harvest_pure_years, retire_absent
from journal_browser.ingest import IngestSession
from journal_browser.models import HarvestRun, Journal, UtWork

ROOT = Path(__file__).resolve().parents[1]


def _load_job(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "jobs" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def test_full_sweep_with_partial_years_is_rejected(db):
    # Regression: --full-sweep used to run over whatever subset was passed and
    # then retire every work last seen in other years' runs.
    with pytest.raises(ValueError, match="full_sweep requires"):
        await harvest_pure_years(db, [2024], full_sweep=True)


async def test_retire_absent_without_runs_is_a_noop(db):
    # `NOT IN ()` renders TRUE: an empty run list must retire nothing.
    assert await retire_absent(db, []) == 0


async def test_headerless_oai_record_is_isolated(db):
    # Regression: one unparseable record used to abort the whole set.
    ingest = IngestSession(db)
    await ingest.start_run("pure", "work", "publications:year2024", {})
    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(([ET.fromstring("<record/>")], {}))
    await queue.put(None)
    stats = {"pages": 0, "new": 0, "duplicate": 0, "deleted": 0, "complete_list_size": None}
    await _consume_oai_pages(ingest, queue, stats, year=2024, entity_type="work", limit=None)
    assert ingest.parse_failures == 1
    assert stats["new"] == 0
    await ingest.finish_run("completed", dict(stats))


async def test_backfill_flags_resets_empty_counts_by_year(db):
    # Regression: journals re-harvested with empty counts_by_year kept stale
    # flags forever (the aggregate never saw them).
    backfill = _load_job("backfill_flags")
    db.add_all(
        [
            Journal(
                issn_l="0000-0001",
                counts_by_year=[],
                works_2020_plus=9,
                last_active_year=2019,
            ),
            Journal(
                issn_l="0000-0002",
                counts_by_year=[{"year": 2022, "works_count": 5}],
                works_2020_plus=0,
            ),
        ]
    )
    await db.commit()
    await db.execute(backfill.UPDATE)
    await db.execute(backfill.RESET_EMPTY)
    one = await db.scalar(select(Journal).where(Journal.issn_l == "0000-0001"))
    two = await db.scalar(select(Journal).where(Journal.issn_l == "0000-0002"))
    assert (one.works_2020_plus, one.last_active_year) == (0, None)
    assert (two.works_2020_plus, two.last_active_year) == (5, 2022)


async def test_verify_ours_counts_active_2020_plus_only(db):
    # Regression: the gate compared ALL ut_works (incl. retired, pre-2020)
    # against ut-metadata's filtered 2020+ corpus.
    verify = _load_job("verify_utmetadata")
    run = HarvestRun(source="t", entity_type="t", config_fingerprint="t", stats={})
    db.add(run)
    await db.flush()
    db.add_all(
        [
            UtWork(
                pure_uuid="a",
                title="A",
                norm_title="a",
                year=2023,
                first_seen_run=run.id,
                last_seen_run=run.id,
            ),
            UtWork(
                pure_uuid="b",
                title="B",
                norm_title="b",
                year=2022,
                first_seen_run=run.id,
                last_seen_run=run.id,
                retired_at=datetime.now(UTC),
            ),
            UtWork(
                pure_uuid="c",
                title="C",
                norm_title="c",
                year=2019,
                first_seen_run=run.id,
                last_seen_run=run.id,
            ),
        ]
    )
    await db.commit()
    stats = await verify.ours(db)
    assert stats["total"] == 1
    assert stats["per_year"] == {2023: 1}


async def test_openapc_invalid_issn_is_counted():
    # Regression: the counter key was never initialized, so the per-row
    # except swallowed the KeyError and mis-filed the row as "skipped".
    rows = [{"issn_l": "1432-7644", "period": "2021", "euro": "100", "doi": "10.1/x"}]
    aggregates, counters = await build_aggregates(rows, _unresolved)
    assert counters["invalid_issn"] == 1
    assert counters["skipped"] == 0
    assert aggregates == []


async def _unresolved(issn):
    return None
