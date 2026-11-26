"""Alembic migration outcomes on a scratch database: head schema carries
the ON CONFLICT constraint names the harvest layer targets, base↔head
is reversible, and 0005 moves APC figures both ways. create_all (the
fixtures' schema source) is not authoritative for migrated deployments.
Replaces test_usage_migration.py and folds in test_schema_contract.py's
constraint assertion; the 0053 browse-marker test retired with the squash
of the migration history."""

import asyncio
import json
import secrets
from collections.abc import Callable
from decimal import Decimal
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
        # Alembic's engines die inside asyncio.run worker threads; without
        # this the FORCE drop waits on their leaked connections.
        await admin.execute(
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
            f" WHERE datname = '{name}' AND pid <> pg_backend_pid()"
        )
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
async def test_apc_list_price_vs_paid_migration_round_trip(mig_db):
    """0005 splits each OpenAPC period by its stored figures, backfills the
    list price and the paid amount, and restores the old figures on the
    way down."""
    _name, url = mig_db
    await _alembic(command.upgrade, "0004_journal_listed_in")
    conn = await asyncpg.connect(url.replace("+asyncpg", ""))

    async def periods() -> dict[tuple[str, int], tuple]:
        """(issn_l, period) -> article count and euro figures."""
        rows = await conn.fetch(
            "select issn_l, period, article_count, euro_min, euro_max, euro_mean"
            " from journal_apc_aggregates order by 1, 2"
        )
        return {
            (r["issn_l"], r["period"]): (
                r["article_count"],
                *(
                    None if r[c] is None else float(r[c])
                    for c in ("euro_min", "euro_max", "euro_mean")
                ),
            )
            for r in rows
        }

    # Figures as the old build_aggregates wrote them: €0 articles count in
    # the lowest amount and the mean, rows without an amount in neither.
    # 0376-7388 2025 (Journal of Membrane Science): articles at €0 under a
    # deal or without an amount; 2024: 2000, 0, 3000.
    # 0034-4257 2024 (Remote Sensing of Environment): 22 paid, 1000..3000.
    old = {
        ("0376-7388", 2024): (3, 0.0, 3000.0, 1666.67),
        ("0376-7388", 2025): (4, 0.0, 0.0, 0.0),
        ("0034-4257", 2024): (22, 1000.0, 3000.0, 2000.0),
        ("0034-4257", 2025): (17, None, None, None),
    }
    for (issn_l, period), (count, lo, hi, mean) in old.items():
        await conn.execute(
            "insert into journal_apc_aggregates"
            " (issn_l, period, article_count, euro_min, euro_max, euro_mean)"
            " values ($1, $2, $3, $4, $5, $6)",
            issn_l,
            period,
            count,
            lo,
            hi,
            mean,
        )
    # The old rule put the newest period's highest amount on the journal,
    # so the deal-paid journal read €0.
    await conn.execute(
        "insert into journals (issn_l, apc_prices, latest_apc_euro) values ($1, $2, 0)",
        "0376-7388",
        json.dumps([{"price": 4890, "currency": "USD"}, {"price": 4460, "currency": "EUR"}]),
    )
    await conn.execute("insert into journals (issn_l, latest_apc_euro) values ('0034-4257', 3000)")
    assert await periods() == old

    await _alembic(command.upgrade, "0005_apc_list_price_vs_paid")

    assert await periods() == {
        # €0 next to paid articles: the mean and highest amount stay, the
        # lowest amount (€0) becomes unknown.
        ("0376-7388", 2024): (3, None, 3000.0, 1666.67),
        # Nothing paid: no euro figure at all.
        ("0376-7388", 2025): (4, None, None, None),
        ("0034-4257", 2024): (22, 1000.0, 3000.0, 2000.0),
        ("0034-4257", 2025): (17, None, None, None),
    }
    counts = {
        (r["issn_l"], r["period"]): (r["paid_count"], r["zero_count"])
        for r in await conn.fetch(
            "select issn_l, period, paid_count, zero_count from journal_apc_aggregates"
        )
    }
    # How many articles were €0 next to paid ones is not stored.
    assert counts == {
        ("0376-7388", 2024): (None, None),
        ("0376-7388", 2025): (0, None),
        ("0034-4257", 2024): (22, 0),
        ("0034-4257", 2025): (0, 0),
    }
    journals = {
        r["issn_l"]: r
        for r in await conn.fetch(
            "select issn_l, latest_apc_euro, latest_apc_period, list_price_source,"
            " list_price_currency, list_price_amount, list_price_euro from journals"
        )
    }
    membrane, remote = journals["0376-7388"], journals["0034-4257"]
    # The paid amount skips the €0 period; the list price comes from OpenAlex.
    assert (float(membrane["latest_apc_euro"]), membrane["latest_apc_period"]) == (1666.67, 2024)
    assert (
        membrane["list_price_source"],
        membrane["list_price_currency"],
        float(membrane["list_price_amount"]),
        float(membrane["list_price_euro"]),
    ) == ("openalex", "EUR", 4460.0, 4460.0)
    assert (float(remote["latest_apc_euro"]), remote["latest_apc_period"]) == (2000.0, 2024)
    assert remote["list_price_source"] is None

    # What the next OpenAPC ingest writes for the mixed period.
    await conn.execute(
        "update journal_apc_aggregates set paid_count = 2, zero_count = 1,"
        " euro_min = 2000, euro_mean = 2500 where issn_l = '0376-7388' and period = 2024"
    )
    await _alembic(command.downgrade, "0004_journal_listed_in")
    assert await periods() == old
    journals = {
        r["issn_l"]: r["latest_apc_euro"]
        for r in await conn.fetch("select issn_l, latest_apc_euro from journals")
    }
    assert journals == {"0376-7388": Decimal(0), "0034-4257": Decimal(3000)}
    columns = {
        r["column_name"]
        for r in await conn.fetch(
            "select column_name from information_schema.columns"
            " where table_schema = 'public' and table_name = 'journals'"
        )
    }
    assert not columns & {"latest_apc_period", "list_price_source", "list_price_euro"}
    await conn.close()
    await _alembic(command.upgrade, "head")


@requires_db
async def test_openalex_funder_ids_bare_up_and_prefixed_back(mig_db):
    """0006 leaves one bare row per OpenAlex funder id: a prefixed twin is
    dropped when the bare row exists and renamed otherwise. The downgrade
    puts a prefixed twin back next to every bare row."""
    _name, url = mig_db
    await _alembic(command.upgrade, "0005_apc_list_price_vs_paid")
    conn = await asyncpg.connect(url.replace("+asyncpg", ""))
    prefix = "https://openalex.org/"
    twins = "F4320320300"
    lone = "F4320320888"
    await conn.execute(
        "insert into openalex_funders (openalex_id, display_name) "
        "values ($1, 'fresh'), ($2, 'stale copy'), ($3, 'old form')",
        twins,
        prefix + twins,
        prefix + lone,
    )
    await conn.execute("insert into jisc_funders (id, name) values (1, 'A'), (2, 'B')")
    await conn.execute(
        "insert into funder_links (funder_id, source, source_id, via) values "
        "(1, 'openalex', $1, 'ror'), (1, 'openalex', $2, 'ror'), "
        "(2, 'openalex', $3, 'fundref')",
        twins,
        prefix + twins,
        prefix + lone,
    )
    await conn.close()

    await _alembic(command.upgrade, "head")
    conn = await asyncpg.connect(url.replace("+asyncpg", ""))
    funders = await conn.fetch(
        "select openalex_id, display_name from openalex_funders order by openalex_id"
    )
    assert [tuple(r.values()) for r in funders] == [(twins, "fresh"), (lone, "old form")]
    links = await conn.fetch(
        "select funder_id, source_id, via from funder_links order by funder_id"
    )
    assert [tuple(r.values()) for r in links] == [(1, twins, "ror"), (2, lone, "fundref")]
    await conn.close()

    await _alembic(command.downgrade, "0005_apc_list_price_vs_paid")
    conn = await asyncpg.connect(url.replace("+asyncpg", ""))
    funders = await conn.fetch(
        "select openalex_id, display_name from openalex_funders order by openalex_id"
    )
    assert [tuple(r.values()) for r in funders] == [
        (twins, "fresh"),
        (lone, "old form"),
        (prefix + twins, "fresh"),
        (prefix + lone, "old form"),
    ]
    links = await conn.fetch(
        "select funder_id, source_id from funder_links order by funder_id, source_id"
    )
    assert [tuple(r.values()) for r in links] == [
        (1, twins),
        (1, prefix + twins),
        (2, lone),
        (2, prefix + lone),
    ]
    await conn.close()

    await _alembic(command.upgrade, "head")  # and 0006 reruns cleanly

    conn = await asyncpg.connect(url.replace("+asyncpg", ""))
    try:
        idx_names = {
            row["indexname"]
            for row in await conn.fetch(
                "SELECT indexname FROM pg_indexes WHERE tablename IN "
                "('source_records', 'apc_evidence', 'authors')"
            )
        }
        assert "ix_source_records_harvest_run_id" in idx_names
        assert "ix_apc_evidence_source_record_id" in idx_names
        assert "ix_authors_name_fold_trgm" in idx_names
    finally:
        await conn.close()
