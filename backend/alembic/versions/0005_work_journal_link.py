"""Link ut_works to resolved journals.

Revision ID: 0005_work_journal_link
Revises: 0004_pure_works
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0005_work_journal_link"
down_revision = "0004_pure_works"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ut_works",
        sa.Column(
            "journal_issn_l", pg.TEXT(), sa.ForeignKey("journals.issn_l"), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("ut_works", "journal_issn_l")
