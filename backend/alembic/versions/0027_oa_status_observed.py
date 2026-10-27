"""Observed OA color: modal oa_status of a journal's recent works.

Revision ID: 0027_oa_status_observed
Revises: 0026_cache_epoch
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0027_oa_status_observed"
down_revision = "0026_cache_epoch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "journals",
        sa.Column("oa_status_observed", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("journals", "oa_status_observed")
