"""Search performance: GIN indexes + denormalized home-stat columns.

Revision ID: 0008_search_denorm
Revises: 0007_corpus_cutoff
Create Date: 2026-10-23
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

# Frozen copies of the denorm SQL as of this revision (the live module moved
# to per-institution journal_flags in 0019; migrations must not drift).
RESET_HOME_WORKS_SQL = text("UPDATE journals SET home_works_count = NULL")
HOME_WORKS_SQL = text(
    """
    UPDATE journals j SET home_works_count = s.n
    FROM (
        SELECT issn_l, sum(works_count) AS n
        FROM (
            SELECT DISTINCT ON (issn_l, year) issn_l, year, works_count
            FROM institution_works_stats
            WHERE institution_id = (SELECT id FROM institutions WHERE is_home)
            ORDER BY issn_l, year, (source = 'pure_canon') DESC
        ) per_year
        GROUP BY issn_l
    ) s
    WHERE j.issn_l = s.issn_l
    """
)
RESET_QUARTILES_SQL = text("UPDATE journals SET latest_quartile = NULL")
QUARTILES_SQL = text(
    """
    UPDATE journals j SET latest_quartile = q.best
    FROM (
        SELECT DISTINCT ON (issn_l) issn_l, best_quartile AS best
        FROM scimagojr_metrics
        WHERE best_quartile IS NOT NULL
        ORDER BY issn_l, year DESC
    ) q
    WHERE j.issn_l = q.issn_l
    """
)
DEAL_FLAGS_SQL = text(
    """
    UPDATE journals j SET deal_covered_home = EXISTS (
        SELECT 1
        FROM deal_journals dj
        JOIN deals d ON d.id = dj.deal_id
        JOIN deal_institutions di ON di.deal_id = d.id
        JOIN institutions i ON i.id = di.institution_id AND i.is_home
        WHERE dj.issn_l = j.issn_l AND d.status = 'current'
    )
    """
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
