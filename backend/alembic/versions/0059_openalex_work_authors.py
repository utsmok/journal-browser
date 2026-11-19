"""openalex_work_authors: attribution edge table.

Revision ID: 0059_openalex_work_authors
Revises: 0058_openalex_author_aids
Create Date: 2026-11-10

Attribution moves off the openalex_works.author_aids array. Array
overlap could not serve faculty-sized org units: a unit's ~1,200 author
ids match most of the store, so the planner skipped the GIN and the
per-row && compare spent ~45 s on the EEMCS gap query (the OR'd jsonb
containment form before it spent ~11 s). One edge row per (work,
lower-cased author id) turns attribution into an indexed probe set via
the author-first PK.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from typing import Sequence, Union

revision: str = "0059_openalex_work_authors"
down_revision: Union[str, None] = "0058_openalex_author_aids"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "openalex_work_authors",
        sa.Column("institution_id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Text(), nullable=False),
        sa.Column("w_id", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("institution_id", "author_id", "w_id"),
    )
    op.drop_index("ix_openalex_works_author_aids_gin", table_name="openalex_works")
    op.drop_column("openalex_works", "author_aids")


def downgrade() -> None:
    op.add_column(
        "openalex_works",
        sa.Column(
            "author_aids", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'")
        ),
    )
    op.create_index(
        "ix_openalex_works_author_aids_gin",
        "openalex_works",
        ["author_aids"],
        postgresql_using="gin",
        postgresql_ops={"author_aids": "array_ops"},
    )
    op.drop_table("openalex_work_authors")
