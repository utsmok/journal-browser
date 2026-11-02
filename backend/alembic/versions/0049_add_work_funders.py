"""Per-work funder/grant rows harvested from OpenAlex works awards.

Revision ID: 0049_add_work_funders
Revises: 0048_add_funder_sources
Create Date: 2026-11-02
"""

import sqlalchemy as sa
from alembic import op

revision = "0049_add_work_funders"
down_revision = "0048_add_funder_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "work_funders",
        sa.Column("institution_id", sa.Integer(), nullable=False),
        sa.Column("pure_uuid", sa.Text(), nullable=False),
        sa.Column("funder_openalex_id", sa.Text(), nullable=False),
        sa.Column("funder_name", sa.Text(), nullable=True),
        sa.Column("award", sa.Text(), nullable=True),
        sa.Column(
            "harvested_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("institution_id", "pure_uuid", "funder_openalex_id"),
        sa.ForeignKeyConstraint(
            ["institution_id", "pure_uuid"],
            ["works.institution_id", "works.pure_uuid"],
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("work_funders")
