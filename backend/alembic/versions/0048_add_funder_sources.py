"""Add funder canon sources: OpenAlex + OpenAIRE funders, JISC ROR/FundRef.

Revision ID: 0048_add_funder_sources
Revises: 0047_jisc_limitations
Create Date: 2026-11-02
"""

import sqlalchemy as sa
from alembic import op

revision = "0048_add_funder_sources"
down_revision = "0047_jisc_limitations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "openalex_funders",
        sa.Column("openalex_id", sa.Text(), nullable=False),
        sa.Column("ror", sa.Text(), nullable=True),
        sa.Column("fundref", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("country_code", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("grant_count", sa.Integer(), nullable=True),
        sa.Column("works_count", sa.Integer(), nullable=True),
        sa.Column("cited_by_count", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("openalex_id"),
    )
    op.create_table(
        "openaire_funders",
        sa.Column("openaire_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("short_name", sa.Text(), nullable=True),
        sa.Column("website_url", sa.Text(), nullable=True),
        sa.Column("jurisdiction", sa.Text(), nullable=True),
        sa.Column("ror", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("openaire_id"),
    )
    op.add_column("jisc_funders", sa.Column("ror", sa.Text(), nullable=True))
    op.add_column("jisc_funders", sa.Column("fundref", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("jisc_funders", "fundref")
    op.drop_column("jisc_funders", "ror")
    op.drop_table("openaire_funders")
    op.drop_table("openalex_funders")
