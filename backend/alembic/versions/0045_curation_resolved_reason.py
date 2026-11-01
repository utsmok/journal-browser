"""deals.curation_resolved_reason: reason-aware curation dismissal.

The old mechanism recorded an admin's needs_curation=False as a
ManualOverride row, which re-applied forever — silently suppressing
every FUTURE curation reason too (the dismissed reason text itself was
overwritten with null and lost). The harvest-owned flag now consults
this column instead: keep the flag cleared while the page produces
exactly this reason; a different reason re-flags.

Upgrade also deletes the legacy needs_curation / needs_curation_reason
override rows: they suppressed new reasons and are superseded by the
column. The deleted rows are not restored on downgrade (they carried
only cleared flags whose reason text was already lost).

Revision ID: 0045_curation_resolved_reason
Revises: 0044_status_change_log
Create Date: 2026-11-01
"""

import sqlalchemy as sa
from alembic import op

revision = "0045_curation_resolved_reason"
down_revision = "0044_status_change_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "deals",
        sa.Column("curation_resolved_reason", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_deals_curation_resolved",
        "deals",
        "needs_curation = false OR curation_resolved_reason IS NULL",
    )
    op.execute(
        "DELETE FROM manual_overrides "
        "WHERE table_name = 'deals' "
        "AND field IN ('needs_curation', 'needs_curation_reason')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_deals_curation_resolved", "deals", type_="check")
    op.drop_column("deals", "curation_resolved_reason")
