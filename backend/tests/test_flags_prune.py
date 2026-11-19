"""journal_flags stays a per-active-institution table.

The 0065 migration prunes rows of inactive institutions, the admin PUT
drops rows on deactivation, and the table shape (constraints, fillfactor)
survives the rebuild. The denorm refresh primitives stay institution-blind:
jobs, loops, and the admin route decide which institutions are served.
"""

import asyncio
import os
import secrets
from pathlib import Path

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from conftest import ADMIN_URL, requires_db
from journal_browser.db import get_session
from journal_browser.harvest.denorm import refresh_deal_flags, refresh_institution_stats
from journal_browser.main import app
from journal_browser.models import Institution, Journal

BACKEND = Path(__file__).resolve().parents[1]
PASSWORD = "test-admin-pw"
ENV_KEYS = ("JB_DATABASE_URL", "JB_SETTINGS_YAML")


async def _alembic(db: str, *steps: tuple[str, str]) -> None:
    """Run alembic against a throwaway DB in a worker thread (env.py calls
    asyncio.run, which cannot nest in the test's event loop). The env vars
    are set only for the run and restored after, so the rest of the test
    session keeps its settings."""
    from journal_browser.config import reset_settings_cache

    saved = {k: os.environ.get(k) for k in ENV_KEYS}
    os.environ["JB_DATABASE_URL"] = f"postgresql+asyncpg://journal:journal@localhost:5433/{db}"
    # A missing settings file: the checkout's settings.yaml must not
    # override the throwaway URL.
    os.environ["JB_SETTINGS_YAML"] = str(BACKEND / "tests" / "_absent_settings.yaml")
    reset_settings_cache()
    try:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(BACKEND / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND / "alembic"))
        for kind, target in steps:
            fn = command.upgrade if kind == "up" else command.downgrade
            await asyncio.to_thread(fn, cfg, target)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_settings_cache()


@pytest.fixture
async def mig_db():
    name = f"journalbrowser_mig_{os.getpid()}_{secrets.token_hex(2)}"
    conn = await asyncpg.connect(ADMIN_URL)
    await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    await conn.execute(f'CREATE DATABASE "{name}"')
    await conn.close()
    try:
        yield name
    finally:
        conn = await asyncpg.connect(ADMIN_URL)
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await conn.close()


async def _seed(db: str) -> dict[str, int]:
    """One active and one inactive institution, three journals, flags rows
    for both institutions (the pre-0065 live shape)."""
    conn = await asyncpg.connect(f"postgresql://journal:journal@localhost:5433/{db}")
    rows = await conn.fetch(
        """
        INSERT INTO institutions (code, name, active) VALUES
            ('miga', 'Mig A', true), ('migb', 'Mig B', false)
        RETURNING id, active
        """
    )
    journals = await conn.fetch(
        """
        INSERT INTO journals (issn_l, title) VALUES
            ('0000-0001', 'A'), ('0000-0002', 'B'), ('0000-0003', 'C')
        RETURNING issn_l
        """
    )
    await conn.executemany(
        "INSERT INTO journal_flags (institution_id, issn_l) VALUES ($1, $2)",
        [(r["id"], j["issn_l"]) for r in rows for j in journals],
    )
    await conn.close()
    return {
        "active": next(r["id"] for r in rows if r["active"]),
        "inactive": next(r["id"] for r in rows if not r["active"]),
    }


@requires_db
async def test_migration_prunes_to_active(mig_db):
    await _alembic(mig_db, ("up", "0064_work_parents"))
    ids = await _seed(mig_db)
    await _alembic(mig_db, ("up", "head"))

    conn = await asyncpg.connect(f"postgresql://journal:journal@localhost:5433/{mig_db}")
    assert await conn.fetchval("SELECT count(*) FROM journal_flags") == 3
    assert (
        await conn.fetchval(
            "SELECT count(*) FROM journal_flags WHERE institution_id = $1", ids["inactive"]
        )
        == 0
    )

    # Shape survives the rebuild: column order, original constraint names,
    # and the HOT fillfactor from 0039.
    cols = await conn.fetch(
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_name = 'journal_flags' ORDER BY ordinal_position"
    )
    assert [c["column_name"] for c in cols] == [
        "institution_id",
        "issn_l",
        "works_count",
        "deal_covered",
        "works_window_plus",
        "browse_excluded",
        "deal_cap_reached",
        "openaire_diamond",
    ]
    cons = {
        r["conname"]
        for r in await conn.fetch(
            "SELECT conname FROM pg_constraint WHERE conrelid = 'journal_flags'::regclass"
        )
    }
    assert cons == {
        "journal_flags_pkey",
        "journal_flags_institution_id_fkey",
        "journal_flags_issn_l_fkey",
    }
    assert "fillfactor=70" in await conn.fetchval(
        "SELECT reloptions FROM pg_class WHERE relname = 'journal_flags'"
    )

    # A search-shaped indexed join still answers for the active institution.
    assert (
        await conn.fetchval(
            "SELECT count(*) FROM journals j JOIN journal_flags f"
            " ON f.issn_l = j.issn_l AND f.institution_id = $1",
            ids["active"],
        )
        == 3
    )
    await conn.close()

    # Downgrade recreates the empty derived shape; a further upgrade runs
    # clean against it.
    await _alembic(mig_db, ("down", "0064_work_parents"), ("up", "head"))
    conn = await asyncpg.connect(f"postgresql://journal:journal@localhost:5433/{mig_db}")
    assert await conn.fetchval("SELECT count(*) FROM journal_flags") == 0
    await conn.close()

    # Denorm refresh re-materializes one row per journal for the active
    # institution; the search join keeps answering.
    engine = create_async_engine(f"postgresql+asyncpg://journal:journal@localhost:5433/{mig_db}")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        inst = await session.scalar(select(Institution).where(Institution.code == "miga"))
        assert inst is not None
        await refresh_institution_stats(session, inst)
        await refresh_deal_flags(session, inst.id)
        await session.commit()
        assert (
            await session.scalar(
                text("SELECT count(*) FROM journal_flags WHERE institution_id = :iid"),
                {"iid": inst.id},
            )
            == 3
        )
        assert (
            await session.execute(
                text(
                    "SELECT j.issn_l FROM journals j JOIN journal_flags f"
                    " ON f.issn_l = j.issn_l AND f.institution_id = :iid"
                ),
                {"iid": inst.id},
            )
        ).scalars().all() == ["0000-0001", "0000-0002", "0000-0003"]
    await engine.dispose()


@pytest.fixture
async def admin_api(db_engine, monkeypatch):
    monkeypatch.setenv("JB_ADMIN_PASSWORD", PASSWORD)
    from journal_browser.config import reset_settings_cache

    reset_settings_cache()
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    async with maker() as session:
        inst = Institution(code="ut", name="UT", active=True)
        session.add(inst)
        await session.flush()
        session.add_all(
            [Journal(issn_l="0000-0001", title="A"), Journal(issn_l="0000-0002", title="B")]
        )
        await session.flush()
        await session.execute(
            text(
                "INSERT INTO journal_flags (institution_id, issn_l)"
                " SELECT :iid, issn_l FROM journals"
            ),
            {"iid": inst.id},
        )
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client
    app.dependency_overrides.clear()
    reset_settings_cache()


async def _login(client: AsyncClient) -> dict[str, str]:
    r = await client.post("/api/v1/admin/login", json={"password": PASSWORD})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


@requires_db
async def test_deactivation_drops_flags(admin_api, db_engine):
    headers = await _login(admin_api)
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _flag_count() -> int:
        async with maker() as session:
            return await session.scalar(text("SELECT count(*) FROM journal_flags"))

    assert await _flag_count() == 2

    # Deactivate: the flags rows go with the flip.
    r = await admin_api.put(
        "/api/v1/admin/institutions/ut", headers=headers, json={"active": False}
    )
    assert r.status_code == 200 and r.json()["active"] is False
    assert await _flag_count() == 0

    # Reactivation is lazy: no rows until the next stats/reconcile run
    # materializes them.
    r = await admin_api.put("/api/v1/admin/institutions/ut", headers=headers, json={"active": True})
    assert r.status_code == 200 and r.json()["active"] is True
    assert await _flag_count() == 0


@requires_db
async def test_denorm_refresh_yields_one_row_per_journal(db, institution_factory):
    active = await institution_factory(code="ut")
    await institution_factory()  # no code: inactive, never materialized
    for issn in ("0000-0001", "0000-0002", "0000-0003"):
        db.add(Journal(issn_l=issn, title=f"J {issn}"))
    await db.commit()

    await refresh_institution_stats(db, active)
    await refresh_deal_flags(db, active.id)

    counts = (
        await db.execute(text("SELECT institution_id, count(*) FROM journal_flags GROUP BY 1"))
    ).all()
    assert counts == [(active.id, 3)]
