"""Allow source='publisher-pattern' on deal_journals.

The reconcile pass derives coverage for openaccess.nl-only deals from the
publisher's journal corpus; the CHECK constraint predates that source.

Revision ID: 0017_deal_journal_source
Revises: 0016_apc_latest_cost
"""

from alembic import op

revision = "0017_deal_journal_source"
down_revision = "0016_apc_latest_cost"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE deal_journals DROP CONSTRAINT ck_deal_journals_source, "
        "ADD CONSTRAINT ck_deal_journals_source "
        "CHECK (source IN ('jct', 'manual', 'publisher-pattern'))"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM deal_journals WHERE source = 'publisher-pattern'"
    )
    op.execute(
        "ALTER TABLE deal_journals DROP CONSTRAINT ck_deal_journals_source, "
        "ADD CONSTRAINT ck_deal_journals_source "
        "CHECK (source IN ('jct', 'manual'))"
    )
