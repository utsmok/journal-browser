"""latest_apc_euro: period mean -> most recent single OpenAPC observation.

Revision ID: 0016_apc_latest_cost
Revises: 0015_issn_lookup_indexes
Create Date: 2026-10-25
"""

from alembic import op
from sqlalchemy import text

from journal_browser.harvest.denorm import APC_SQL

revision = "0016_apc_latest_cost"
down_revision = "0015_issn_lookup_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Column shape is unchanged; only the value semantics move from the
    # latest period's euro_mean to the newest reported single cost.
    # Reset only populated rows: a blanket UPDATE rewrites all 177k journals
    # rows (slow with the embedding + FTS indexes); APC_SQL re-stamps every
    # row this touches.
    bind = op.get_bind()
    bind.execute(
        text("UPDATE journals SET latest_apc_euro = NULL WHERE latest_apc_euro IS NOT NULL")
    )
    bind.execute(APC_SQL)


def downgrade() -> None:
    # No structural change to undo; recomputing period means here would
    # duplicate refresh_apcs logic, so leave values as-is.
    pass
