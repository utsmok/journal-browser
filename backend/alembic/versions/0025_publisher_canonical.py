"""Publisher canonicalization: OpenAlex lineage root per journal.

Revision ID: 0025_publisher_canonical
Revises: 0024_author_confirmation
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0025_publisher_canonical"
down_revision = "0024_author_confirmation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Grouping key for the publishers surface: NULL/empty falls back to
    # publisher_name, so pre-harvest rows keep today's grouping.
    op.add_column("journals", sa.Column("publisher_canonical", sa.Text(), nullable=True))
    # Lineage cache (jobs/harvest_publishers.py): one row per OpenAlex
    # publisher entity attempted; a failed fetch stays as a row with NULL
    # lineage so re-runs do not re-fetch it.
    op.create_table(
        "openalex_publishers",
        sa.Column("openalex_id", pg.TEXT(), primary_key=True),
        sa.Column("display_name", pg.TEXT(), nullable=True),
        sa.Column("lineage", pg.JSONB(), nullable=True),
        sa.Column("canonical_id", pg.TEXT(), nullable=True),
        sa.Column("canonical_name", pg.TEXT(), nullable=True),
        sa.Column("fetched_at", pg.TIMESTAMP(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("openalex_publishers")
    op.drop_column("journals", "publisher_canonical")
