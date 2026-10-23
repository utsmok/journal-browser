"""Deal register links column + trigram index for OpenAIRE title matching.

Revision ID: 0010_deal_links_and_match
Revises: 0008_search_denorm
Create Date: 2026-10-23
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0010_deal_links_and_match"
down_revision = "0009_search_scopes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("deals", sa.Column("links", JSONB(astext_type=sa.Text()), nullable=True))
    # pg_trgm % join in harvest/openaire.py plans nested-loop without this.
    # IF NOT EXISTS: the dev DB got this index hand-created ahead of the
    # migration; a plain CREATE INDEX would abort `upgrade head` there.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ut_works_norm_title_trgm"
        " ON ut_works USING gin (norm_title gin_trgm_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_ut_works_norm_title_trgm", table_name="ut_works")
    op.drop_column("deals", "links")
