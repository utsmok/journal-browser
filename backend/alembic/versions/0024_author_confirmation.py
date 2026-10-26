"""Author browsing: affiliation confirmation + search facet columns.

Revision ID: 0024_author_confirmation
Revises: 0023_authors
Create Date: 2026-10-26
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0024_author_confirmation"
down_revision = "0023_authors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "institutions",
        sa.Column(
            "require_confirmed_affiliation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "authors",
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("authors", sa.Column("last_pub_year", sa.Integer(), nullable=True))
    op.add_column("authors", sa.Column("primary_topic", pg.TEXT(), nullable=True))


def downgrade() -> None:
    op.drop_column("authors", "primary_topic")
    op.drop_column("authors", "last_pub_year")
    op.drop_column("authors", "confirmed")
    op.drop_column("institutions", "require_confirmed_affiliation")
