"""Add deal_journals.excluded: admin removals survive re-harvest.

Removed rows are flagged, never deleted, so the JCT upsert cannot
resurrect them; the denormalized deal-coverage SQL filters them out.

Revision ID: 0021_deal_journal_excluded
Revises: 0020_embedding_hnsw
"""

import sqlalchemy as sa
from alembic import op

revision = "0021_deal_journal_excluded"
down_revision = "0020_embedding_hnsw"


def upgrade() -> None:
    op.add_column(
        "deal_journals",
        sa.Column("excluded", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("deal_journals", "excluded")
