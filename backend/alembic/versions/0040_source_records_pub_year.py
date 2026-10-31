"""source_records: mirror publication_year out of the verbatim payload.

The journal-detail serving path (_journal_works) filters each institution's
publication-year window inside the JSONB, so every candidate row's ~8 KB
payload detoasts before the window drops it. A real nullable column plus a
partial index over the works_stats slice lets DISTINCT ON + window run
pre-detoast (measured: 162 ms -> ~50 ms per works fetch on live data).

Backfill reads the projection from the payload itself; rows without an
integer publication_year stay NULL and drop out of windows exactly as the
old astext path did.

Revision ID: 0040_source_records_pub_year
Revises: 0039_reclaim_flags_authorships
Create Date: 2026-10-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0040_source_records_pub_year"
down_revision: Union[str, None] = "0039_reclaim_flags_authorships"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "ix_source_records_works_year"


def upgrade() -> None:
    op.add_column(
        "source_records",
        sa.Column("publication_year", sa.Integer(), nullable=True),
    )
    op.execute(
        """
        UPDATE source_records
        SET publication_year = (payload->>'publication_year')::int
        WHERE source = 'openalex'
          AND entity_type = 'works_stats'
          AND payload->>'publication_year' ~ '^[0-9]+$'
        """
    )
    op.execute(
        f"""
        CREATE INDEX {INDEX_NAME} ON source_records
        USING btree (publication_year, source_pk, harvested_at DESC)
        WHERE source = 'openalex' AND entity_type = 'works_stats'
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
    op.drop_column("source_records", "publication_year")
