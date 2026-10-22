"""Search performance: GIN indexes + denormalized home-stat columns.

Revision ID: 0008_search_denorm
Revises: 0007_corpus_cutoff
Create Date: 2026-10-23
"""

import sqlalchemy as sa
from alembic import op

from journal_browser.harvest.denorm import (
    DEAL_FLAGS_SQL,
    HOME_WORKS_SQL,
    QUARTILES_SQL,
    RESET_HOME_WORKS_SQL,
    RESET_QUARTILES_SQL,
)

revision = "0008_search_denorm"
down_revision = "0007_corpus_cutoff"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("journals", sa.Column("home_works_count", sa.Integer(), nullable=True))
    op.add_column("journals", sa.Column("latest_quartile", sa.String(length=4), nullable=True))
    op.add_column(
        "journals",
        sa.Column(
            "deal_covered_home",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    bind = op.get_bind()
    bind.execute(RESET_HOME_WORKS_SQL)
    bind.execute(HOME_WORKS_SQL)
    bind.execute(RESET_QUARTILES_SQL)
    bind.execute(QUARTILES_SQL)
    bind.execute(DEAL_FLAGS_SQL)
    op.execute("CREATE INDEX ix_journals_search_vector ON journals USING gin (search_vector)")
    op.execute(
        "CREATE INDEX ix_journals_search_text_trgm ON journals USING gin (search_text gin_trgm_ops)"
    )
    op.execute("CREATE INDEX ix_journals_topics_gin ON journals USING gin (topics jsonb_path_ops)")


def downgrade() -> None:
    op.drop_index("ix_journals_topics_gin", table_name="journals")
    op.drop_index("ix_journals_search_text_trgm", table_name="journals")
    op.drop_index("ix_journals_search_vector", table_name="journals")
    op.drop_column("journals", "deal_covered_home")
    op.drop_column("journals", "latest_quartile")
    op.drop_column("journals", "home_works_count")
