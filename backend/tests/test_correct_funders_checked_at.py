"""works.funders_checked_at (migration 0069) gates the work-funders
harvest: fresh-stamped works skip the sweep, zero-award works get stamped
per chunk so they leave the nightly sweep, and the migration itself is
reversible."""

import asyncio
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, update

from conftest import ADMIN_URL, requires_db
from journal_browser.harvest.work_funders import harvest_work_funders
from journal_browser.models import HarvestRun, Work, WorkFunder

BACKEND_DIR = Path(__file__).resolve().parents[1]


async def _alembic(fn, rev: str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    await asyncio.to_thread(fn, cfg, rev)


@pytest.fixture
async def mig_db(monkeypatch):
    """A unique scratch database with JB_DATABASE_URL pointed at it (same
    shape as test_migrations.mig_db)."""
    name = f"journalbrowser_mig_{secrets.token_hex(3)}"
    url = f"postgresql+asyncpg://journal:journal@localhost:5433/{name}"
    admin = await asyncpg.connect(ADMIN_URL)
    await admin.execute(f'CREATE DATABASE "{name}"')
    monkeypatch.setenv("JB_DATABASE_URL", url)
    from journal_browser.config import reset_settings_cache

    reset_settings_cache()
    try:
        yield name, url
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()
        reset_settings_cache()


@requires_db
async def test_0069_up_down_reversible(mig_db):
    _name, url = mig_db
    await _alembic(command.upgrade, "head")
    conn = await asyncpg.connect(url.replace("+asyncpg", ""))
    cols = await conn.fetch(
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_name = 'works' AND column_name = 'funders_checked_at'"
    )
    assert len(cols) == 1
    await conn.close()

    await _alembic(command.downgrade, "0068_openalex_export_columns")
    conn = await asyncpg.connect(url.replace("+asyncpg", ""))
    cols = await conn.fetch(
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_name = 'works' AND column_name = 'funders_checked_at'"
    )
    assert cols == []
    await conn.close()
    await _alembic(command.upgrade, "head")


def _payload(doi: str, awards: list[dict]):
    """Minimal OpenAlex work object: id + awards, plus the model_dump the
    ingest session stores."""
    return SimpleNamespace(
        id=f"https://openalex.org/W-{doi}",
        awards=awards,
        model_dump=lambda mode="json": {"id": f"W-{doi}", "awards": awards},
    )


@pytest.fixture
async def sweep_fixture(db, institution_factory, monkeypatch):
    ut = await institution_factory(code="ut", data_window_start=2020)
    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    db.add(run)
    await db.flush()
    db.add_all(
        [
            Work(
                institution_id=ut.id,
                pure_uuid="w-awarded",
                title="w-awarded",
                norm_title="w-awarded",
                year=2023,
                doi_normalized="10.0.0/awarded",
                first_seen_run=run.id,
                last_seen_run=run.id,
            ),
            Work(
                institution_id=ut.id,
                pure_uuid="w-bare",
                title="w-bare",
                norm_title="w-bare",
                year=2023,
                doi_normalized="10.0.0/bare",
                first_seen_run=run.id,
                last_seen_run=run.id,
            ),
        ]
    )
    await db.commit()

    async def _fake_fetch(_client, dois, stats=None):
        # One work with awards, one OpenAlex reports without any.
        return (
            {
                doi: _payload(
                    doi,
                    [{"funder_id": "https://openalex.org/F-1"}] if doi == "10.0.0/awarded" else [],
                )
                for doi in dois
            },
            set(),
            None,
        )

    monkeypatch.setattr("journal_browser.harvest.work_funders.fetch_works_by_doi", _fake_fetch)
    return ut


@requires_db
async def test_sweep_stamps_zero_award_and_respects_ttl(db, sweep_fixture):
    stats = await harvest_work_funders(db, ttl_days=30)
    assert stats["works_attempted"] == 2
    rows = (await db.execute(select(Work.pure_uuid, Work.funders_checked_at))).all()
    stamps = {r.pure_uuid: r.funders_checked_at for r in rows}
    # Zero-award works are stamped too: they leave the sweep.
    assert stamps["w-awarded"] is not None and stamps["w-bare"] is not None
    wf = (await db.execute(select(WorkFunder))).scalars().all()
    assert [(w.pure_uuid, w.funder_openalex_id) for w in wf] == [("w-awarded", "F-1")]

    stats2 = await harvest_work_funders(db, ttl_days=30)
    assert stats2["works_attempted"] == 0

    # Beyond the TTL the works become eligible again.
    await db.execute(update(Work).values(funders_checked_at=datetime.now(UTC) - timedelta(days=31)))
    stats3 = await harvest_work_funders(db, ttl_days=30)
    assert stats3["works_attempted"] == 2


@requires_db
async def test_sweep_skips_fresh_works(db, sweep_fixture):
    await db.execute(update(Work).values(funders_checked_at=datetime.now(UTC)))
    stats = await harvest_work_funders(db, ttl_days=30)
    assert stats["works_attempted"] == 0
    assert stats["skipped_fresh"] == stats["works_with_doi"] == 2
    assert (await db.execute(select(WorkFunder))).scalars().all() == []


@requires_db
async def test_errored_fetch_keeps_works_eligible(db, sweep_fixture, monkeypatch):
    async def _failing_fetch(_client, _dois, stats=None):
        if stats is not None:
            stats["fetch_errors"] = 2
        raise RuntimeError("openalex down")

    monkeypatch.setattr("journal_browser.harvest.work_funders.fetch_works_by_doi", _failing_fetch)
    with pytest.raises(RuntimeError, match="openalex down"):
        await harvest_work_funders(db, ttl_days=30)
    stamps = (await db.execute(select(Work.funders_checked_at))).scalars().all()
    # Failed chunks stamp nothing: the next run retries every work.
    assert all(s is None for s in stamps)
