"""Journal language: modal OpenAlex work language per journal.

Revision ID: 0054_journal_language
Revises: 0053_usage_browse_marker
Create Date: 2026-11-05

journals.language is filled by the openalex_works rebuild (modal work
language per venue), so the upgrade backfill is a no-op — the next rebuild
stamps it.
"""

import sqlalchemy as sa
from alembic import op

revision = "0054_journal_language"
down_revision = "0053_usage_browse_marker"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("openalex_works", sa.Column("language", sa.Text(), nullable=True))
    op.add_column("journals", sa.Column("language", sa.String(8), nullable=True))


def downgrade() -> None:
    op.drop_column("journals", "language")
    op.drop_column("openalex_works", "language")
