"""Author browsing: per-institution authors + author-work membership.

Revision ID: 0023_authors
Revises: 0022_drop_is_default
Create Date: 2026-10-26
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0023_authors"
down_revision = "0022_drop_is_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "authors",
        sa.Column(
            "institution_id",
            sa.Integer(),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("pure_uuid", pg.TEXT(), primary_key=True),
        sa.Column("name", pg.TEXT(), nullable=False),
        sa.Column("orcid", pg.TEXT(), nullable=True),
        sa.Column("openalex_author_id", pg.TEXT(), nullable=True),
        sa.Column("openaire_person_id", pg.TEXT(), nullable=True),
        sa.Column("crossref_orcid", pg.TEXT(), nullable=True),
        sa.Column("faculty", pg.TEXT(), nullable=True),
        sa.Column("research_group", pg.TEXT(), nullable=True),
        sa.Column("orgs", pg.JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("n_works", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            pg.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_table(
        "author_works",
        sa.Column(
            "institution_id",
            sa.Integer(),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("author_pure_uuid", pg.TEXT(), primary_key=True),
        sa.Column("work_pure_uuid", pg.TEXT(), primary_key=True),
        sa.ForeignKeyConstraint(
            ["institution_id", "author_pure_uuid"],
            ["authors.institution_id", "authors.pure_uuid"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id", "work_pure_uuid"],
            ["works.institution_id", "works.pure_uuid"],
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("author_works")
    op.drop_table("authors")
