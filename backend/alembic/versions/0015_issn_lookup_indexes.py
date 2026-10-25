"""ISSN lookup indexes: normalized ISSN matching + reverse ISSN-L mapping.

Revision ID: 0015_issn_lookup_indexes
Revises: 0014_journal_apc_denorm
Create Date: 2026-10-25
"""

from alembic import op

revision = "0015_issn_lookup_indexes"
down_revision = "0014_journal_apc_denorm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The search ISSN path matches upper(replace(issn, '-', '')), which no
    # existing index serves; issn_map seq-scanned 269k rows per ISSN query.
    op.execute("CREATE INDEX IF NOT EXISTS ix_issn_map_issn_norm ON issn_map (upper(replace(issn, '-', '')))")
    # Reverse map: resolve an ISSN-L back to all its ISSN variants.
    op.execute("CREATE INDEX IF NOT EXISTS ix_issn_map_issn_l ON issn_map (issn_l)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_issn_map_issn_l")
    op.execute("DROP INDEX IF EXISTS ix_issn_map_issn_norm")
