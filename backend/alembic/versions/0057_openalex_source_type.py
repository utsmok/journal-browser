"""OpenAlex primary-location source type on openalex_works.

Revision ID: 0057_openalex_source_type
Revises: 0056_people_utwente
Create Date: 2026-11-10

Gap queries drop repository-typed store rows: a repository copy (Zenodo,
TNO repository) is not evidence a work is missing from Pure, and the
institution's own research information system is repository-typed in
OpenAlex. The upgrade backfill is a no-op — the next openalex_works
rebuild projects the column from the stored raw payloads (0054's language
column works the same way).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0057_openalex_source_type"
down_revision: Union[str, None] = "0056_people_utwente"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("openalex_works", sa.Column("source_type", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("openalex_works", "source_type")
