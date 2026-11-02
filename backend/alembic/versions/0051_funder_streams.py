"""OpenAIRE funder funding streams: top level-0 facets per funder.

Revision ID: 0051_funder_streams
Revises: 0050_funder_links
Create Date: 2026-11-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TIMESTAMP

revision = "0051_funder_streams"
down_revision = "0050_funder_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "openaire_funder_streams",
        sa.Column("funder_openaire_id", sa.Text(), nullable=False),
        sa.Column("level0_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("n_projects", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["funder_openaire_id"],
            ["openaire_funders.openaire_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("funder_openaire_id", "level0_id"),
    )


def downgrade() -> None:
    op.drop_table("openaire_funder_streams")
