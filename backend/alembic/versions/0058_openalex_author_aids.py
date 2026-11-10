"""openalex_works.author_aids: array-overlap attribution probe.

Revision ID: 0058_openalex_author_aids
Revises: 0057_openalex_source_type
Create Date: 2026-11-10

The gap queries attributed works by OR-ing one jsonb containment probe
per author id (both case forms): faculty-sized units built ~2,400 OR'd
probes, the planner refused the bitmap-OR over that many index paths and
seq-scanned 300k rows — the EEMCS org-unit page took ~11 s. A lower-cased
bare-id text[] with a GIN (array_ops) index answers the same "names any
of these authors" question with one overlap probe, indexed.

The upgrade backfill is a no-op — the next openalex_works rebuild
projects the column (like language and source_type). The jsonb GIN index
on authorships had no remaining containment consumer and drops.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0058_openalex_author_aids"
down_revision: Union[str, None] = "0057_openalex_source_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "openalex_works",
        sa.Column("author_aids", postgresql.ARRAY(sa.Text()), nullable=False,
                  server_default=sa.text("'{}'")),
    )
    op.create_index(
        "ix_openalex_works_author_aids_gin",
        "openalex_works",
        ["author_aids"],
        postgresql_using="gin",
        postgresql_ops={"author_aids": "array_ops"},
    )
    op.drop_index("ix_openalex_works_authorships_gin", table_name="openalex_works")


def downgrade() -> None:
    op.create_index(
        "ix_openalex_works_authorships_gin",
        "openalex_works",
        ["authorships"],
        postgresql_using="gin",
        postgresql_ops={"authorships": "jsonb_path_ops"},
    )
    op.drop_index("ix_openalex_works_author_aids_gin", table_name="openalex_works")
    op.drop_column("openalex_works", "author_aids")
