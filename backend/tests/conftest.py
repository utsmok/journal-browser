"""Test fixtures: an isolated throwaway database per session."""

import asyncio
import os

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.models import Base

TEST_DB = "journalbrowser_pytest"
ADMIN_URL = "postgresql://journal:journal@localhost:5433/journalbrowser"
TEST_URL = f"postgresql+asyncpg://journal:journal@localhost:5433/{TEST_DB}"


def _db_reachable() -> bool:
    try:
        asyncio.run(asyncpg.connect(ADMIN_URL, timeout=3))
        return True
    except Exception:
        return False


DB_AVAILABLE = _db_reachable() or bool(os.environ.get("JB_TEST_DB"))

requires_db = pytest.mark.skipif(
    not DB_AVAILABLE, reason="no local Postgres; CI provides one on 5433"
)


@pytest.fixture
async def db_engine():
    # Function-scoped: pytest-asyncio runs each test in its own event loop,
    # and an asyncpg pool must not cross loops.
    if not DB_AVAILABLE:
        pytest.skip("no database")
    conn = await asyncpg.connect(ADMIN_URL)
    await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
    await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
    await conn.close()
    engine = create_async_engine(TEST_URL)
    async with engine.begin() as conn:
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
