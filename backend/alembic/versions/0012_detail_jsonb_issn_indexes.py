"""Partial JSONB expression indexes for journal detail/works lookups.

Revision ID: 0012_detail_jsonb_issn_indexes
Revises: 0011_browse_excluded
Create Date: 2026-10-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0012_detail_jsonb_issn_indexes"
down_revision = "0011_browse_excluded"
branch_labels = None
depends_on = None

# Expressions must match the ORM filters verbatim (services/
# detail_enrichment.py): payload->>'issn_l' for venue sources rows,
# payload->'primary_location'->'source'->>'issn_l' for works_stats rows.
# Without these, every detail/works request seq-scans the 3.4 GB
# source_records landing store (measured: 3.0 s for the sources lookup,
# 1.8 s for the works filter).
SOURCES_INDEX = "ix_source_records_sources_issn_l"
WORKS_INDEX = "ix_source_records_works_issn_l"


def upgrade() -> None:
    op.create_index(
        SOURCES_INDEX,
        "source_records",
        [sa.text("(payload ->> 'issn_l')"), sa.text("harvested_at DESC")],
        postgresql_where=sa.text("(source = 'openalex') AND (entity_type = 'sources')"),
    )
    op.create_index(
        WORKS_INDEX,
        "source_records",
        [
            sa.text("((payload -> 'primary_location' -> 'source') ->> 'issn_l')"),
            sa.text("source_pk"),
            sa.text("harvested_at DESC"),
        ],
        postgresql_where=sa.text("(source = 'openalex') AND (entity_type = 'works_stats')"),
    )


def downgrade() -> None:
    op.drop_index(WORKS_INDEX, table_name="source_records")
    op.drop_index(SOURCES_INDEX, table_name="source_records")
