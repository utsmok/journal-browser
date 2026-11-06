"""Dump the public schema of a journal-browser database to JSON.

The /data-pipeline page renders the database section from this dump, so the
page cannot drift from the real schema. The script only runs SELECT queries
against information_schema and pg_catalog; it never writes.

Usage:
    cd backend && uv run python scripts/dump_db_schema.py \
        --dsn postgresql://journal:journal@127.0.0.1:5434/journalbrowser \
        --out ../frontend/lib/data-pipeline-schema.json

The alembic_version table is excluded: it is migration bookkeeping, not
domain data.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import asyncpg

TABLES_SQL = """
select table_name, table_type
from information_schema.tables
where table_schema = 'public' and table_name <> 'alembic_version'
order by table_name
"""

COLUMNS_SQL = """
select table_name, column_name, data_type, udt_name, is_nullable,
       column_default, ordinal_position, character_maximum_length,
       numeric_precision, numeric_scale
from information_schema.columns
where table_schema = 'public'
order by table_name, ordinal_position
"""

KEY_CONSTRAINTS_SQL = """
select tc.table_name, tc.constraint_name, tc.constraint_type,
       kcu.column_name, kcu.ordinal_position
from information_schema.table_constraints tc
join information_schema.key_column_usage kcu
  on kcu.constraint_name = tc.constraint_name
 and kcu.constraint_schema = tc.constraint_schema
where tc.table_schema = 'public'
  and tc.constraint_type in ('PRIMARY KEY', 'UNIQUE')
order by tc.table_name, tc.constraint_name, kcu.ordinal_position
"""

FOREIGN_KEYS_SQL = """
select tc.table_name, tc.constraint_name,
       kcu.column_name, kcu.ordinal_position,
       ccu.table_name as foreign_table, ccu.column_name as foreign_column,
       rc.update_rule, rc.delete_rule
from information_schema.table_constraints tc
join information_schema.key_column_usage kcu
  on kcu.constraint_name = tc.constraint_name
 and kcu.constraint_schema = tc.constraint_schema
join information_schema.constraint_column_usage ccu
  on ccu.constraint_name = tc.constraint_name
 and ccu.constraint_schema = tc.constraint_schema
join information_schema.referential_constraints rc
  on rc.constraint_name = tc.constraint_name
 and rc.constraint_schema = 'public'
where tc.table_schema = 'public'
  and tc.constraint_type = 'FOREIGN KEY'
order by tc.table_name, tc.constraint_name, kcu.ordinal_position
"""

CHECKS_SQL = """
select rel.relname as table_name, con.conname as constraint_name,
       pg_get_constraintdef(con.oid) as definition
from pg_constraint con
join pg_class rel on rel.oid = con.conrelid
join pg_namespace nsp on nsp.oid = rel.relnamespace
where nsp.nspname = 'public' and con.contype = 'c'
order by rel.relname, con.conname
"""

INDEXES_SQL = """
select tablename, indexname, indexdef
from pg_indexes
where schemaname = 'public'
order by tablename, indexname
"""


def render_type(row: asyncpg.Record) -> str:
    data_type = row["data_type"]
    udt = row["udt_name"]
    if data_type == "ARRAY":
        base = udt.lstrip("_")
        return f"{base}[]"
    if data_type == "USER-DEFINED":
        return udt
    if data_type == "character":
        length = row["character_maximum_length"]
        return f"varchar({length})" if length is not None else "varchar"
    if data_type == "numeric":
        precision, scale = row["numeric_precision"], row["numeric_scale"]
        if precision is None:
            return "numeric"
        if scale:
            return f"numeric({precision},{scale})"
        return f"numeric({precision})"
    return data_type


async def dump(dsn: str) -> dict:
    conn = await asyncpg.connect(dsn)

    async def fetch(sql: str) -> list[asyncpg.Record]:
        return await conn.fetch(sql)

    try:
        tables = await fetch(TABLES_SQL)
        columns = await fetch(COLUMNS_SQL)
        key_constraints = await fetch(KEY_CONSTRAINTS_SQL)
        foreign_keys = await fetch(FOREIGN_KEYS_SQL)
        checks = await fetch(CHECKS_SQL)
        indexes = await fetch(INDEXES_SQL)
    finally:
        await conn.close()

    result: dict[str, dict] = {}
    for row in tables:
        kind = "view" if row["table_type"] == "VIEW" else "table"
        result[row["table_name"]] = {
            "name": row["table_name"],
            "kind": kind,
            "columns": [],
            "primaryKey": [],
            "uniques": [],
            "foreignKeys": [],
            "checks": [],
            "indexes": [],
        }

    for row in columns:
        table = result.get(row["table_name"])
        if table is None:
            continue
        default = row["column_default"]
        table["columns"].append(
            {
                "name": row["column_name"],
                "type": render_type(row),
                "nullable": row["is_nullable"] == "YES",
                "default": default,
            }
        )

    for row in key_constraints:
        table = result.get(row["table_name"])
        if table is None:
            continue
        if row["constraint_type"] == "PRIMARY KEY":
            table["primaryKey"].append(row["column_name"])
        else:
            existing = next(
                (u for u in table["uniques"] if u["name"] == row["constraint_name"]),
                None,
            )
            if existing is None:
                table["uniques"].append(
                    {"name": row["constraint_name"], "columns": [row["column_name"]]}
                )
            else:
                existing["columns"].append(row["column_name"])

    for row in foreign_keys:
        table = result.get(row["table_name"])
        if table is None:
            continue
        existing = next(
            (f for f in table["foreignKeys"] if f["name"] == row["constraint_name"]),
            None,
        )
        if existing is None:
            table["foreignKeys"].append(
                {
                    "name": row["constraint_name"],
                    "columns": [row["column_name"]],
                    "toTable": row["foreign_table"],
                    "toColumns": [row["foreign_column"]],
                    "onUpdate": row["update_rule"],
                    "onDelete": row["delete_rule"],
                }
            )
        else:
            existing["columns"].append(row["column_name"])
            existing["toColumns"].append(row["foreign_column"])

    for row in checks:
        table = result.get(row["table_name"])
        if table is None:
            continue
        table["checks"].append({"name": row["constraint_name"], "definition": row["definition"]})

    for row in indexes:
        table = result.get(row["tablename"])
        if table is None:
            continue
        table["indexes"].append({"name": row["indexname"], "definition": row["indexdef"]})

    return {
        "generatedAt": datetime.now(UTC).strftime("%Y-%m-%d"),
        "tables": [result[name] for name in sorted(result)],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", required=True, help="postgresql:// DSN, read-only use")
    parser.add_argument("--out", required=True, help="output JSON path")
    args = parser.parse_args()

    data = asyncio.run(dump(args.dsn))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2) + "\n")
    tables = len(data["tables"])
    columns = sum(len(t["columns"]) for t in data["tables"])
    print(f"wrote {out_path}: {tables} tables, {columns} columns")


if __name__ == "__main__":
    main()
