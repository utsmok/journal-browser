"""Test fixtures: an isolated throwaway database per session.

Database tests are mandatory: a missing/unreachable Postgres fails the run
loudly unless JB_SKIP_DB_TESTS=1 explicitly opts out.
"""

import asyncio
import os
import secrets

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.db import get_session
from journal_browser.models import Base, Journal

# Tests stay offline: the fastembed model must never load (main imports it
# eagerly at create_app time). conftest is imported before test modules, so
# this also covers test files that import journal_browser.main themselves.
os.environ.setdefault("JB_SKIP_EMBEDDING_WARMUP", "1")

# Admin ops (CREATE/DROP DATABASE) go through the always-present maintenance
# db, not `journalbrowser`: the CI service only creates journalbrowser_test.
ADMIN_URL = "postgresql://journal:journal@localhost:5433/postgres"
# Unique per process: two concurrent pytest runs must not fight over one DB.
TEST_DB = (
    os.environ.get("JB_TEST_DB") or f"journalbrowser_pytest_{os.getpid()}_{secrets.token_hex(2)}"
)
TEST_URL = f"postgresql+asyncpg://journal:journal@localhost:5433/{TEST_DB}"

# Services that build their own engine from settings (flags_refresh) must
# hit the throwaway DB too, never the shared dev DB.
os.environ.setdefault("JB_DATABASE_URL", TEST_URL)

# Keyless OpenAlex semantics for every test: no test may depend on a real
# key or budget. pydantic skips empty env values and falls through the
# AliasChoices chain, so BOTH names must be emptied; aletheca's own env
# fallbacks too. _offline_openalex keeps the credits helper offline.
os.environ["JB_OPENALEX_API_KEY"] = ""
os.environ["OPENALEX_API_KEY"] = ""
os.environ["ALETHECA_API_KEY"] = ""
os.environ["ALETHECA_OPENALEX_API_KEY"] = ""


def _db_reachable() -> bool:
    try:
        asyncio.run(asyncpg.connect(ADMIN_URL, timeout=3))
        return True
    except Exception:
        return False


SKIP_DB_REASON = "JB_SKIP_DB_TESTS=1 set: database tests skipped by explicit opt-out"

if os.environ.get("JB_SKIP_DB_TESTS") == "1":
    requires_db = pytest.mark.skip(reason=SKIP_DB_REASON)
elif not _db_reachable():
    raise RuntimeError(
        "Database tests require Postgres on localhost:5433 (journal/journal). "
        "Start the dev DB or set JB_SKIP_DB_TESTS=1 to skip them explicitly."
    )
else:
    # DB presence is asserted above; nothing to skip.
    def requires_db(fn):
        return fn


@pytest.fixture(autouse=True)
def _offline_openalex(monkeypatch):
    """Keep the suite off the live OpenAlex budget: the credits helper
    returns None (gate open, zero HTTP) even if settings.yaml carries an
    API key. Tests that exercise the gate must mock the helper explicitly."""

    async def _no_credits() -> float | None:
        return None

    monkeypatch.setattr("journal_browser.harvest.common.openalex_credits_remaining", _no_credits)


@pytest.fixture(scope="session")
def _test_db():
    """Create the throwaway database and its schema once per process.

    Sync on purpose: pytest-asyncio runs each test in its own event loop,
    so neither the admin connection nor the schema engine may live in a
    fixture that outlives one test. Per-test work (truncate) happens in
    the function-scoped `db_engine` below.
    """
    if os.environ.get("JB_SKIP_DB_TESTS") == "1":
        pytest.skip(SKIP_DB_REASON)

    async def _create() -> None:
        conn = await asyncpg.connect(ADMIN_URL)
        await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
        await conn.close()

    asyncio.run(_create())

    async def _build() -> None:
        engine = create_async_engine(TEST_URL)
        async with engine.begin() as conn:
            # journals.embedding is a vector column; the pgvector type must
            # exist before create_all issues the table DDL.
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(_build())
    yield

    async def _drop() -> None:
        conn = await asyncpg.connect(ADMIN_URL)
        await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
        await conn.close()

    asyncio.run(_drop())


@pytest.fixture
async def db_engine(_test_db):
    from journal_browser.services import cache, repo_links, source_health

    cache.FACET_CACHE.clear()
    cache.SNAPSHOT_CACHE.clear()
    cache.SWR_CACHE.clear()
    repo_links.reset_canon_cache()
    source_health.clear_all()
    # Fresh database per test at truncate cost instead of drop/create +
    # create_all: the schema is identical every run, only the rows differ.
    # A failed request can leak an app session that stays idle in
    # transaction and would block the truncate, so drop those first —
    # the old drop-database-with-FORCE teardown did this implicitly.
    tables = ", ".join(f'"{t}"' for t in sorted(Base.metadata.tables))
    engine = create_async_engine(TEST_URL)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
                " WHERE datname = current_database() AND pid <> pg_backend_pid()"
            )
        )
        await conn.exec_driver_sql(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")
    yield engine
    # Admin-write tests spawn background tasks (flags_refresh) whose pools
    # die with the test's event loop; terminate their connections here so
    # they cannot accumulate into a slow final database drop.
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
                " WHERE datname = current_database() AND pid <> pg_backend_pid()"
            )
        )
    await engine.dispose()


@pytest.fixture
async def db(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()


@pytest.fixture
def institution_factory(db):
    """Hosted institution rows for multi-institution tests.

    Usage: `inst = await institution_factory(code="ut")`. Codes default to
    unique per call.
    """
    from journal_browser.models import Institution

    counter = {"n": 0}

    async def _make(
        *,
        code: str | None = None,
        name: str | None = None,
        data_window_start: int = 2020,
        data_window_end: int | None = None,
        **kwargs,
    ) -> Institution:
        counter["n"] += 1
        n = counter["n"]
        inst = Institution(
            code=code,
            name=name or f"Test University {n}",
            ror=kwargs.pop("ror", f"https://ror.org/test{n:04d}"),
            active=code is not None,
            data_window_start=data_window_start,
            data_window_end=data_window_end,
            **kwargs,
        )
        db.add(inst)
        await db.flush()
        return inst

    return _make


def journal_factory(issn_l: str, **kw) -> Journal:
    """Union of the ten former per-file _journal() defaults."""
    base = {
        "issn_l": issn_l,
        "title": f"Journal {issn_l}",
        "search_text": f"Journal {issn_l}",
        "type": "journal",
        "is_oa": False,
        "is_in_doaj": False,
        "in_scimago": False,
        "works_2020_plus": 10,
    }
    base.update(kw)
    return Journal(**base)


def pair_rows(*works):
    """Attribution edges for the given openalex_works rows under test —
    the same derivation the store rebuild applies to its authorships."""
    from journal_browser.models import OpenalexWorkAuthor

    return [
        OpenalexWorkAuthor(
            institution_id=work.institution_id,
            author_id=aid,
            w_id=work.w_id,
        )
        for work in works
        for aid in sorted({a["a"].lower() for a in (work.authorships or []) if a.get("a")})
    ]


@pytest.fixture
async def client(db_engine):
    from journal_browser.main import app

    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://t")
    app.dependency_overrides.clear()
