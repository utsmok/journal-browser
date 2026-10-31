"""authors: institute attribute (MESA+ / TechMed / DSI separation).

Institutes are organisationally separate from faculties (owner ruling):
they must be browsable as their own orgunit level and never contribute
faculty evidence. The column mirrors faculty/research_group — derived at
ingest from pure person CERIF affiliations (profile first, canonical-person
work-level arm as fallback); full-replace ingest backfills it, so the
migration adds the nullable column only.

Revision ID: 0041_authors_institute
Revises: 0040_source_records_pub_year
Create Date: 2026-10-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0041_authors_institute"
down_revision: Union[str, None] = "0040_source_records_pub_year"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("authors", sa.Column("institute", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("authors", "institute")
