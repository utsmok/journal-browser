"""openalex_work_parents: registry of parent works named by the store.

Revision ID: 0064_work_parents
Revises: 0063_work_parts
Create Date: 2026-11-16

One row per (institution, parent W-id) the openalex_works.parent_works
arrays name (a chapter's book, a figure's paper).
jobs/backfill_parts.py fills title/doi/work_type with one free
single-entity GET per parent. Pure registration is derived at query
time (EXISTS on doi_normalized against the works table) — a parent
without a DOI cannot match and counts as unregistered.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0064_work_parents"
down_revision: Union[str, None] = "0063_work_parts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "openalex_work_parents",
        sa.Column("institution_id", sa.Integer(), nullable=False),
        sa.Column("parent_w_id", sa.Text(), nullable=False),
        sa.Column("doi_normalized", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("work_type", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("institution_id", "parent_w_id"),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("openalex_work_parents")
