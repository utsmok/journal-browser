"""openalex_works work-parts columns (OpenAlex Graph v12 parent_works).

Revision ID: 0063_work_parts
Revises: 0062_openaire_work_facts
Create Date: 2026-11-16

parent_works/is_part drive the standalone/chapter/part work filter and
the chapter rollups; parts_checked_at is the per-DOI backfill's skip
marker (rows harvested before Graph v12 carry no parent_works in their
stored payloads).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0063_work_parts"
down_revision: Union[str, None] = "0062_openaire_work_facts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "openalex_works",
        sa.Column(
            "parent_works",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column(
        "openalex_works",
        sa.Column("is_part", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "openalex_works",
        sa.Column("parts_checked_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("openalex_works", "parts_checked_at")
    op.drop_column("openalex_works", "is_part")
    op.drop_column("openalex_works", "parent_works")
