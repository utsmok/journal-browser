"""Performance: reclaim journal_flags bloat, index openalex_works.authorships.

The nightly flags refresh rewrites rows non-HOT; on long-lived deployments
journal_flags grows ~100x its data size (measured live: 19 MB data in a
2.1 GB heap, 269k pages), and every seq scan over it pays the read back —
the journal-search counts, facet aggregates, and orgunit deal rollups all
scan it. Rebuild the heap once and lower the fillfactor so future nightly
refreshes update in place (HOT).

The GIN (jsonb_path_ops) index turns the author profile's authorship
containment OR-chain into index scans (~95 ms -> ~5 ms per profile read).

Revision ID: 0039_reclaim_flags_authorships
Revises: 0038_limitation_code_rename
Create Date: 2026-10-31
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0039_reclaim_flags_authorships"
down_revision: Union[str, None] = "0038_limitation_code_rename"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "ix_openalex_works_authorships_gin"


def upgrade() -> None:
    # VACUUM FULL cannot run inside a transaction; the rewrite holds an
    # ACCESS EXCLUSIVE lock for a few seconds on a 2 GB heap. At deploy time
    # the backend runs this before serving, so no traffic hits the lock.
    with op.get_context().autocommit_block():
        op.execute("VACUUM FULL journal_flags")
        op.execute("ALTER TABLE journal_flags SET (fillfactor = 70)")
    # Raw DDL: SQLAlchemy's create_index parenthesizes text() columns into
    # expressions, which is invalid for the "column opclass" grammar.
    op.execute(
        f"CREATE INDEX {INDEX_NAME} ON openalex_works USING gin (authorships jsonb_path_ops)"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
    with op.get_context().autocommit_block():
        op.execute("ALTER TABLE journal_flags SET (fillfactor = 100)")
