"""Mark default browse loads among usage search events (is_browse).

Revision ID: 0053_usage_browse_marker
Revises: 0052_usage_events
Create Date: 2026-11-04

Downgrade drops is_browse; the query strings the upgrade backfill nulled on
browse rows are lost, which is acceptable — they were empty strings by
definition and carried no information.
"""

import sqlalchemy as sa
from alembic import op

revision = "0053_usage_browse_marker"
down_revision = "0052_usage_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "usage_events",
        sa.Column("is_browse", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Empty string was the client's implicit "default browse load" sentinel;
    # make it an explicit flag and drop the useless query text.
    op.execute(
        "UPDATE usage_events SET is_browse = true, query = NULL "
        "WHERE event_type = 'search' AND query = ''"
    )


def downgrade() -> None:
    op.drop_column("usage_events", "is_browse")
