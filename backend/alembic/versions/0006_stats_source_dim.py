"""Stats source dimension: pure_canon vs openalex_institution_filter.

Revision ID: 0006_stats_source_dim
Revises: 0005_work_journal_link
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_stats_source_dim"
down_revision = "0005_work_journal_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "institution_works_stats",
        sa.Column(
            "source", sa.Text(), nullable=False,
            server_default="openalex_institution_filter",
        ),
    )
    op.execute("ALTER TABLE institution_works_stats DROP CONSTRAINT institution_works_stats_pkey")
    op.create_primary_key(
        "institution_works_stats_pkey",
        "institution_works_stats",
        ["institution_id", "source", "issn_l", "year"],
    )


def downgrade() -> None:
    op.execute("DELETE FROM institution_works_stats WHERE source <> 'openalex_institution_filter'")
    op.execute("ALTER TABLE institution_works_stats DROP CONSTRAINT institution_works_stats_pkey")
    op.create_primary_key(
        "institution_works_stats_pkey",
        "institution_works_stats",
        ["institution_id", "issn_l", "year"],
    )
    op.drop_column("institution_works_stats", "source")
