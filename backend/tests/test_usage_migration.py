"""Migration 0053: is_browse column add + empty-query backfill, reversible."""

import asyncio
import secrets
from collections.abc import Callable
from pathlib import Path

import asyncpg
from alembic import command
from alembic.config import Config

from conftest import ADMIN_URL, requires_db
from journal_browser.config import reset_settings_cache

BACKEND_DIR = Path(__file__).resolve().parents[1]


async def _alembic(fn: Callable[..., None], rev: str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    # env.py calls asyncio.run(); a worker thread has no running loop.
    await asyncio.to_thread(fn, cfg, rev)


@requires_db
async def test_0053_browse_marker_up_down_up(monkeypatch):
    name = f"journalbrowser_mig_{secrets.token_hex(3)}"
    url = f"postgresql+asyncpg://journal:journal@localhost:5433/{name}"
    admin = await asyncpg.connect(ADMIN_URL)
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
        monkeypatch.setenv("JB_DATABASE_URL", url)
        reset_settings_cache()

        await _alembic(command.upgrade, "0052_usage_events")
        seed = await asyncpg.connect(url.replace("+asyncpg", ""))
        await seed.execute(
            "INSERT INTO usage_events (session_id, event_type, path, query) VALUES "
            "('s', 'search', '/ut', ''),"
            "('s', 'search', '/ut', 'gold'),"
            "('s', 'page_view', '/ut', NULL)"
        )

        await _alembic(command.upgrade, "0053_usage_browse_marker")
        rows = await seed.fetch("SELECT event_type, query, is_browse FROM usage_events ORDER BY id")
        assert [(r["event_type"], r["query"], r["is_browse"]) for r in rows] == [
            ("search", None, True),
            ("search", "gold", False),
            ("page_view", None, False),
        ]

        await _alembic(command.downgrade, "0052_usage_events")
        cols = await seed.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'usage_events' AND column_name = 'is_browse'"
        )
        assert cols == []

        await seed.close()
        await _alembic(command.upgrade, "0053_usage_browse_marker")
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()
        reset_settings_cache()
