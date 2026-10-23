"""Test fixtures: an isolated throwaway database per session.

Database tests are mandatory: a missing/unreachable Postgres fails the run
loudly unless JB_SKIP_DB_TESTS=1 explicitly opts out.
"""

import asyncio
import os
import secrets

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.models import Base

ADMIN_URL = "postgresql://journal:journal@localhost:5433/journalbrowser"
# Unique per process: two concurrent pytest runs must not fight over one DB.
TEST_DB = (
    os.environ.get("JB_TEST_DB") or f"journalbrowser_pytest_{os.getpid()}_{secrets.token_hex(2)}"
)
TEST_URL = f"postgresql+asyncpg://journal:journal@localhost:5433/{TEST_DB}"


def _db_reachable() -> bool:
    try:
        asyncio.run(asyncpg.connect(ADMIN_URL, timeout=3))
        return True
    except Exception:
        return False


if os.environ.get("JB_SKIP_DB_TESTS") == "1":
    requires_db = pytest.mark.skip(
        reason="JB_SKIP_DB_TESTS=1 set: database tests skipped by explicit opt-out"
    )
elif not _db_reachable():
    raise RuntimeError(
        "Database tests require Postgres on localhost:5433 (journal/journal). "
        "Start the dev DB or set JB_SKIP_DB_TESTS=1 to skip them explicitly."
    )
else:
    # DB presence is asserted above; nothing to skip.
    def requires_db(fn):
        return fn


@pytest.fixture
async def db_engine():
    # Function-scoped: pytest-asyncio runs each test in its own event loop,
    # and an asyncpg pool must not cross loops.
    conn = await asyncpg.connect(ADMIN_URL)
    await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
    await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
    await conn.close()
    engine = create_async_engine(TEST_URL)
    async with engine.begin() as conn:
        # journals.embedding is a vector column; the pgvector type must
        # exist before create_all issues the table DDL.
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()
    conn = await asyncpg.connect(ADMIN_URL)
    await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
    await conn.close()


@pytest.fixture
async def db(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
