"""journals.listed_in: OpenAlex curated-list memberships for the
recommendation eligibility rule (services/search/recommendable.py).

Backfilled from the newest stored OpenAlex source payload per journal, so
recommendations filter correctly before the next source sweep.

Revision ID: 0004_journal_listed_in
Revises: 0003_collaborations_v2
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004_journal_listed_in"
down_revision: Union[str, None] = "0003_collaborations_v2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "journals",
        sa.Column("listed_in", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.execute(
        """
        UPDATE journals j
        SET listed_in = (
            SELECT CASE
                WHEN jsonb_typeof(r.payload->'listed_in') = 'array' THEN r.payload->'listed_in'
                ELSE '[]'::jsonb
            END
            FROM source_records r
            WHERE r.source = 'openalex'
              AND r.entity_type = 'sources'
              AND r.source_pk = j.openalex_id
            ORDER BY r.harvested_at DESC
            LIMIT 1
        )
        WHERE j.openalex_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_column("journals", "listed_in")
