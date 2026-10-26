"""Drop institutions.is_default: no default institution once more than one exists.

Revision ID: 0022_drop_is_default
Revises: 0021_deal_journal_excluded
Create Date: 2026-10-26
"""

import sqlalchemy as sa
from alembic import op

revision = "0022_drop_is_default"
down_revision = "0021_deal_journal_excluded"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("institutions", "is_default")


def downgrade() -> None:
    op.add_column(
        "institutions",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
