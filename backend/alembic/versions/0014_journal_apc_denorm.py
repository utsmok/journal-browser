"""Denormalized latest APC column for results-table sorting.

Revision ID: 0014_journal_apc_denorm
Revises: 0013_journal_embeddings
Create Date: 2026-10-25
"""

import sqlalchemy as sa
from alembic import op

from journal_browser.harvest.denorm import APC_SQL

revision = "0014_journal_apc_denorm"
down_revision = "0013_journal_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("journals", sa.Column("latest_apc_euro", sa.Numeric(), nullable=True))
    # No RESET pass here: the column was just created, every row is NULL
    # already, and a blanket UPDATE would rewrite all rows (slow with the
    # embedding + FTS indexes). RESET_APC_SQL only matters on re-harvest.
    op.get_bind().execute(APC_SQL)


def downgrade() -> None:
    op.drop_column("journals", "latest_apc_euro")
