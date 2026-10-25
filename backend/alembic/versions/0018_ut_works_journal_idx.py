"""Index ut_works.journal_issn_l for detail-page lookups.

openaire_matched (services/detail_enrichment.py) filters on the column on
every journal-detail request; without the index each view seq-scans the
~300k works table.

Revision ID: 0018_ut_works_journal_idx
Revises: 0017_deal_journal_source
"""

from alembic import op

revision = "0018_ut_works_journal_idx"
down_revision = "0017_deal_journal_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_ut_works_journal_issn_l ON ut_works (journal_issn_l) "
        "WHERE journal_issn_l IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_ut_works_journal_issn_l", table_name="ut_works")
