"""Schema-name contract: constraint names the harvest code targets with
ON CONFLICT must exist after `alembic upgrade head` — create_all (the
test fixtures' schema source) is not authoritative for migrated
deployments. Regression: enrich/openaire used a constraint name that
existed in no world, and only crashed on the first real duplicate
(mid-harvest on a migrated database)."""

import asyncio
import os
import uuid

import asyncpg
from sqlalchemy import text

from conftest import ADMIN_URL, requires_db
from journal_browser.models import WORK_IDENTITY_UQ

# Every ON CONFLICT constraint literal the harvest layer targets.
WANTED_CONSTRAINTS = {
    "work_identity": [WORK_IDENTITY_UQ],
}


@requires_db
async def test_migrated_schema_has_conflict_constraints(db_engine) -> None:
    """Upgrade a scratch database through alembic (not create_all) and
    check each ON CONFLICT target exists by name in pg_constraint."""
    from alembic import command
    from alembic.config import Config

    dbname = f"jb_schema_contract_{uuid.uuid4().hex[:8]}"
    scratch = f"{ADMIN_URL.rsplit('/', 1)[0]}/{dbname}".replace(
        "postgresql://", "postgresql+asyncpg://"
    )

    conn = await asyncpg.connect(ADMIN_URL)
    await conn.execute(f'CREATE DATABASE "{dbname}"')
    await conn.close()

    # env.py reads JB_DATABASE_URL through cached get_settings; point both
    # at the scratch database for the upgrade.
    from journal_browser.config import get_settings

    old_url = os.environ.get("JB_DATABASE_URL")
    os.environ["JB_DATABASE_URL"] = scratch
    get_settings.cache_clear()
    try:
        await asyncio.to_thread(lambda: command.upgrade(Config("alembic.ini"), "head"))
    finally:
        if old_url is None:
            os.environ.pop("JB_DATABASE_URL", None)
        else:
            os.environ["JB_DATABASE_URL"] = old_url
        get_settings.cache_clear()

    try:
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(scratch, echo=False)
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "select relname as tbl, conname from pg_constraint c "
                        "join pg_class r on r.oid = c.conrelid "
                        "where c.contype = 'u' and relname = any(:t)"
                    ),
                    {"t": list(WANTED_CONSTRAINTS)},
                )
            ).all()
        await engine.dispose()
        by_table: dict[str, set[str]] = {}
        for tbl, con in rows:
            by_table.setdefault(tbl, set()).add(con)
        for tbl, names in WANTED_CONSTRAINTS.items():
            got = by_table.get(tbl, set())
            missing = set(names) - got
            assert not missing, f"{tbl}: missing constraints {missing}, has {got}"
    finally:
        conn = await asyncpg.connect(ADMIN_URL)
        await conn.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')
        await conn.close()
