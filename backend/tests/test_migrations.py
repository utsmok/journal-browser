"""Alembic migration outcomes on a scratch database: head schema carries
the ON CONFLICT constraint names the harvest layer targets, base↔head is
reversible, and 0053's browse marker backfills and downgrades cleanly.
create_all (the fixtures' schema source) is not authoritative for
migrated deployments. Replaces test_usage_migration.py and folds in
test_schema_contract.py's constraint assertion."""

import asyncio
import secrets
from collections.abc import Callable
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config

from conftest import ADMIN_URL, requires_db
from journal_browser.config import reset_settings_cache
from journal_browser.models import WORK_IDENTITY_UQ

BACKEND_DIR = Path(__file__).resolve().parents[1]


async def _alembic(fn: Callable[..., None], rev: str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    # env.py calls asyncio.run(); a worker thread has no running loop.
    await asyncio.to_thread(fn, cfg, rev)


@pytest.fixture
async def mig_db(monkeypatch):
    """A unique scratch database with JB_DATABASE_URL pointed at it."""
    name = f"journalbrowser_mig_{secrets.token_hex(3)}"
    url = f"postgresql+asyncpg://journal:journal@localhost:5433/{name}"
    admin = await asyncpg.connect(ADMIN_URL)
    await admin.execute(f'CREATE DATABASE "{name}"')
    monkeypatch.setenv("JB_DATABASE_URL", url)
    reset_settings_cache()
    try:
        yield name, url
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()
        reset_settings_cache()


@requires_db
async def test_upgrade_head_down_base_up_head(mig_db):
    _name, url = mig_db
    await _alembic(command.upgrade, "head")

    engine_conn = await asyncpg.connect(url.replace("+asyncpg", ""))
    rows = await engine_conn.fetch(
        "select conname from pg_constraint c join pg_class r on r.oid = c.conrelid "
        "where c.contype = 'u' and relname = 'work_identity'"
    )
    assert WORK_IDENTITY_UQ in {r["conname"] for r in rows}  # ON CONFLICT target exists
    await engine_conn.close()

    await _alembic(command.downgrade, "base")
    conn = await asyncpg.connect(url.replace("+asyncpg", ""))
    tables = await conn.fetch(
        "select tablename from pg_tables where schemaname = 'public' "
        "and tablename != 'alembic_version'"
    )
    assert tables == []  # base really is empty
    await conn.close()

    await _alembic(command.upgrade, "head")  # and the tree reinstalls cleanly


@requires_db
async def test_0053_browse_marker_up_down_up(mig_db):
    _name, url = mig_db
    sync_url = url.replace("+asyncpg", "")
    await _alembic(command.upgrade, "0052_usage_events")
    seed = await asyncpg.connect(sync_url)
    await seed.execute(
        "INSERT INTO usage_events (session_id, event_type, path, query) VALUES "
        "('s', 'search', '/ut', ''),"
        "('s', 'search', '/ut', 'gold'),"
        "('s', 'page_view', '/ut', NULL)"
    )

    await _alembic(command.upgrade, "0053_usage_browse_marker")
    rows = await seed.fetch("SELECT event_type, query, is_browse FROM usage_events ORDER BY id")
    assert [(r["event_type"], r["query"], r["is_browse"]) for r in rows] == [
        ("search", None, True),  # empty query counts as browse
        ("search", "gold", False),
        ("page_view", None, False),
    ]

    await _alembic(command.downgrade, "0052_usage_events")
    cols = await seed.fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'usage_events' AND column_name = 'is_browse'"
    )
    assert cols == []  # the column is gone again
    await seed.close()
