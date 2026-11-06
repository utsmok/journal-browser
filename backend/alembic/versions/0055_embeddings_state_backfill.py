"""Backfill the bootstrap plan-completion marker where vectors exist.

Bootstrap's auto mode requires harvest_state to show a completed plan run
(source local / entity_type bootstrap_plan) before it will skip.
Deployments that predate the marker never wrote one, but journal vectors
mean the embeddings step, the plan's last step, ran to completion, so
seed the marker once for them. Fresh databases have no journals at
upgrade time and get no row; the plan runner writes the marker itself.

Revision ID: 0055_embeddings_state_backfill
Revises: 0054_journal_language
"""

from alembic import op

revision = "0055_embeddings_state_backfill"
down_revision = "0054_journal_language"
branch_labels = None
depends_on = None

MARKER_WHERE = "source = 'local' AND entity_type = 'bootstrap_plan' AND institution_id IS NULL"


def upgrade() -> None:
    op.execute(
        "INSERT INTO harvest_state "
        "  (source, entity_type, filter_set, institution_id, status, stats, updated_at) "
        "SELECT 'local', 'bootstrap_plan', 'backfill', NULL, 'completed', "
        "       '{\"backfilled\": true}'::jsonb, now() "
        "WHERE NOT EXISTS (SELECT 1 FROM harvest_state WHERE " + MARKER_WHERE + ") "
        "  AND EXISTS (SELECT 1 FROM journals WHERE embedding IS NOT NULL)"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM harvest_state WHERE " + MARKER_WHERE + "   AND stats->>'backfilled' = 'true'"
    )
