"""Promote the CSV-export payload fields to openalex_works columns.

The publisher/journal gap CSV read four small cells (publication_date,
pdf_url, landing_page_url, institution_rors) from the full works_stats
payload per row — tens of KB of TOASTed jsonb per work — which dominated
the export's runtime. The harvest now projects the same four values into
columns (raw_export_fields); this migration adds the columns and backfills
them from the latest works_stats source_record per W-id, the exact payload
the export's lateral used to pick.

The backfill reproduces raw_export_fields in SQL: COALESCE chains for the
two url cells and a distinct sorted ';'-join over
authorships[].institutions[].ror. Rows without a stored works_stats
payload stay NULL (the export rendered empty cells for those, and still
does).

Downgrade drops the columns; the harvest repopulates them on the next
rebuild.

Revision ID: 0068_openalex_export_columns
Revises: 0067_drop_crossref_meta
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0068_openalex_export_columns"
down_revision: str | None = "0067_drop_crossref_meta"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = ("publication_date", "pdf_url", "landing_page_url", "institution_rors")

_BACKFILL = """
WITH latest AS (
    SELECT DISTINCT ON (source_pk) source_pk, payload
    FROM source_records
    WHERE source = 'openalex' AND entity_type = 'works_stats'
    ORDER BY source_pk, harvested_at DESC, id DESC
)
UPDATE openalex_works ow
SET publication_date = l.payload ->> 'publication_date',
    pdf_url = COALESCE(
        l.payload #>> '{best_oa_location,pdf_url}',
        l.payload #>> '{primary_location,pdf_url}'
    ),
    landing_page_url = COALESCE(
        l.payload #>> '{primary_location,landing_page_url}',
        l.payload #>> '{best_oa_location,landing_page_url}'
    ),
    institution_rors = COALESCE((
        SELECT string_agg(r.ror, ';' ORDER BY r.ror)
        FROM (
            SELECT DISTINCT i ->> 'ror' AS ror
            FROM jsonb_array_elements(
                CASE WHEN jsonb_typeof(l.payload -> 'authorships') = 'array'
                     THEN l.payload -> 'authorships'
                     ELSE '[]'::jsonb END
            ) AS a
            CROSS JOIN LATERAL jsonb_array_elements(
                CASE WHEN jsonb_typeof(a -> 'institutions') = 'array'
                     THEN a -> 'institutions'
                     ELSE '[]'::jsonb END
            ) AS i
        ) r
        WHERE r.ror IS NOT NULL
    ), '')
FROM latest l
WHERE ow.w_id = l.source_pk
"""


def upgrade() -> None:
    for name in _COLUMNS:
        op.add_column("openalex_works", sa.Column(name, sa.Text(), nullable=True))
    op.execute(_BACKFILL)


def downgrade() -> None:
    for name in reversed(_COLUMNS):
        op.drop_column("openalex_works", name)
