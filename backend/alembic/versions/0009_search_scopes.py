"""Search scopes: trigram indexes for publisher/topic ILIKE + corpus PK index.

Revision ID: 0009_search_scopes
Revises: 0008_search_denorm
Create Date: 2026-10-23
"""

from alembic import op

revision = "0009_search_scopes"
down_revision = "0009_limitations_refresh"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_journals_publisher_name_trgm "
        "ON journals USING gin (publisher_name gin_trgm_ops)"
    )
    # ILIKE over topic display names goes through the JSONB text cast.
    op.execute(
        "CREATE INDEX ix_journals_topics_text_trgm "
        "ON journals USING gin ((topics::text) gin_trgm_ops)"
    )
    # Count-covering experiment for the browse-all filter (see search.py
    # WORKS_CUTOFF): keep only if the planner actually picks it.
    op.execute(
        "CREATE INDEX ix_journals_issn_l_corpus ON journals (issn_l) "
        "WHERE works_2020_plus > 3 AND type = 'journal' AND issn_l IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_journals_issn_l_corpus", table_name="journals")
    op.drop_index("ix_journals_topics_text_trgm", table_name="journals")
    op.drop_index("ix_journals_publisher_name_trgm", table_name="journals")
