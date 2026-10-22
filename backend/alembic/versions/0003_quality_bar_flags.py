"""Quality-bar derived flags (decisions.md #12).

Revision ID: 0003_quality_bar
Revises: 0002_limitations
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_quality_bar"
down_revision = "0002_limitations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("journals", sa.Column("last_active_year", sa.Integer(), nullable=True))
    op.add_column(
        "journals",
        sa.Column(
            "is_active_recently", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column(
        "journals",
        sa.Column("in_scimago", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("journals", "in_scimago")
    op.drop_column("journals", "is_active_recently")
    op.drop_column("journals", "last_active_year")
