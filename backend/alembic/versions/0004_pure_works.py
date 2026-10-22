"""Pure works: canonical UT works + cross-source work identity.

Revision ID: 0004_pure_works
Revises: 0003_quality_bar_flags
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0004_pure_works"
down_revision = "0003_quality_bar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "ut_works",
        sa.Column("pure_uuid", pg.TEXT(), primary_key=True),
        sa.Column("doi_normalized", pg.TEXT(), nullable=True, unique=True),
        sa.Column("title", pg.TEXT(), nullable=False),
        sa.Column("norm_title", pg.TEXT(), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("work_type", pg.TEXT(), nullable=True),
        sa.Column("publisher", pg.TEXT(), nullable=True),
        sa.Column("cerif_issn", pg.TEXT(), nullable=True),
        sa.Column("oa_status", pg.TEXT(), nullable=True),
        sa.Column(
            "first_seen_run", sa.BigInteger(), sa.ForeignKey("harvest_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_run", sa.BigInteger(), sa.ForeignKey("harvest_runs.id"),
            nullable=False,
        ),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
    )
    op.create_index("ix_ut_works_year", "ut_works", ["year"])
    op.create_index("ix_ut_works_norm_title", "ut_works", ["norm_title"])

    op.create_table(
        "work_identity",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source", pg.TEXT(), nullable=False),
        sa.Column("source_pk", pg.TEXT(), nullable=False),
        sa.Column(
            "ut_work_id", pg.TEXT(),
            sa.ForeignKey("ut_works.pure_uuid", ondelete="CASCADE"), nullable=False,
        ),
        # doi | trgm:<threshold>[+v][+a] | verbatim
        sa.Column("matched_by", pg.TEXT(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        # candidate | confirmed | rejected
        sa.Column("status", pg.TEXT(), nullable=False, server_default="candidate"),
        sa.Column("note", pg.TEXT(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.UniqueConstraint("source", "source_pk", name="uq_work_identity_source"),
    )
    op.create_index("ix_work_identity_ut_work", "work_identity", ["ut_work_id"])
    op.create_index("ix_work_identity_status", "work_identity", ["status"])


def downgrade() -> None:
    op.drop_table("work_identity")
    op.drop_table("ut_works")
