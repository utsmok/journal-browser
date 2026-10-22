"""Corpus cutoff: works_2020_plus replaces the quality-bar flag.

Revision ID: 0007_corpus_cutoff
Revises: 0006_stats_source_dim
Create Date: 2026-10-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_corpus_cutoff"
down_revision = "0006_stats_source_dim"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "journals",
        sa.Column("works_2020_plus", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute(
        """
        UPDATE journals
        SET works_2020_plus = coalesce(y.total, 0)
        FROM (
            SELECT issn_l, sum((e->>'works_count')::int) AS total
            FROM journals, jsonb_array_elements(counts_by_year) e
            WHERE (e->>'year')::int >= 2020
            GROUP BY issn_l
        ) y
        WHERE journals.issn_l = y.issn_l
        """
    )
    op.drop_column("journals", "is_active_recently")
    op.create_index(
        "ix_journals_works_2020_plus",
        "journals",
        ["works_2020_plus"],
        postgresql_where=sa.text("works_2020_plus > 3"),
    )


def downgrade() -> None:
    op.drop_index("ix_journals_works_2020_plus", table_name="journals")
    op.add_column(
        "journals",
        sa.Column(
            "is_active_recently", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.execute(
        """
        UPDATE journals
        SET is_active_recently = (works_2020_plus > 0)
        """
    )
    op.drop_column("journals", "works_2020_plus")
