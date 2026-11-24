"""pg_stat_statements: per-statement totals for finding slow queries.

The extension can only be created on a server that preloads its library.
compose starts db with shared_preload_libraries=pg_stat_statements
(DEPLOYMENT.md, "Query statistics"); CI's Postgres does not preload it, so
the migration skips the extension there and the schema still migrates.

Revision ID: 0007_pg_stat_statements
Revises: 0006_bare_openalex_funder_ids
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_pg_stat_statements"
down_revision: Union[str, None] = "0006_bare_openalex_funder_ids"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    preloaded = op.get_bind().scalar(sa.text("SHOW shared_preload_libraries")) or ""
    if "pg_stat_statements" in preloaded:
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pg_stat_statements")
