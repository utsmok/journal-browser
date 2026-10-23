"""Denormalized browse_excluded flag for the proceedings-series exclusion.

Revision ID: 0011_browse_excluded
Revises: 0010_deal_links_and_match
Create Date: 2026-10-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_browse_excluded"
down_revision = "0010_deal_links_and_match"
branch_labels = None
depends_on = None

# Same predicate as harvest/denorm.py BROWSE_EXCLUDED_SQL; kept in sync so
# the migration backfill and job refreshes agree.
BACKFILL_SQL = """
    UPDATE journals SET browse_excluded =
        (coalesce(title, '') ~*
         '\\y(conference|proceedings|symposium|workshop|abstracts|meetings)\\y')
        AND NOT deal_covered_home
        AND coalesce(home_works_count, 0) = 0
"""


def upgrade() -> None:
    op.add_column(
        "journals",
        sa.Column("browse_excluded", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.execute(BACKFILL_SQL)


def downgrade() -> None:
    op.drop_column("journals", "browse_excluded")
