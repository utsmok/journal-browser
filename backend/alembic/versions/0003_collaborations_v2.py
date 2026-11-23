"""Collaborations v2: searchable ROR aliases/acronyms, conservative parent &
successor roll-ups, work partner counts (for mega-collab filtering), and
home-institution corresponding authorship.

Revision ID: 0003_collaborations_v2
Revises: 0002_collaborations
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003_collaborations_v2"
down_revision: Union[str, None] = "0002_collaborations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("partner_institutions", sa.Column("search_text", sa.Text(), nullable=True))
    op.add_column(
        "partner_institutions",
        sa.Column("acronyms", postgresql.ARRAY(sa.Text()), nullable=True),
    )
    op.add_column("partner_institutions", sa.Column("rollup_ror", sa.Text(), nullable=True))
    op.create_index(
        "ix_partner_institutions_rollup_ror",
        "partner_institutions",
        ["rollup_ror"],
    )
    op.execute(
        "CREATE INDEX ix_partner_institutions_search_trgm "
        "ON partner_institutions USING gin (search_text gin_trgm_ops)"
    )

    op.add_column(
        "work_partners",
        sa.Column(
            "home_corresponding",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "work_partners",
        sa.Column(
            "partner_count",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_work_partners_inst_count",
        "work_partners",
        ["institution_id", "partner_count"],
    )

    # Backfill work_partners.partner_count from existing links so standard/small
    # collaboration-size filters work immediately after migration.
    op.execute(
        """
        WITH counts AS (
            SELECT institution_id, work_pure_uuid, count(*)::int AS n
            FROM work_partners
            GROUP BY institution_id, work_pure_uuid
        )
        UPDATE work_partners wp
        SET partner_count = counts.n
        FROM counts
        WHERE wp.institution_id = counts.institution_id
          AND wp.work_pure_uuid = counts.work_pure_uuid
        """
    )

    # Backfill partner_institutions.search_text and acronyms from stored ROR
    # payloads, names, and cities.
    op.execute(
        """
        UPDATE partner_institutions pi
        SET
            search_text = lower(
                concat_ws(
                    ' | ',
                    pi.name,
                    pi.city,
                    pi.ror,
                    (
                        SELECT string_agg(DISTINCT btrim(n->>'value'), ' | ')
                        FROM jsonb_array_elements(coalesce(pi.payload->'names', '[]'::jsonb)) n
                        WHERE nullif(btrim(n->>'value'), '') IS NOT NULL
                    )
                )
            ),
            acronyms = (
                SELECT array_agg(DISTINCT lower(btrim(n->>'value')))
                FROM jsonb_array_elements(coalesce(pi.payload->'names', '[]'::jsonb)) n
                WHERE nullif(btrim(n->>'value'), '') IS NOT NULL
                  AND (
                      (n->'types') ? 'acronym'
                      OR ((n->'types') ? 'alias' AND char_length(btrim(n->>'value')) <= 16)
                  )
            )
        """
    )


def downgrade() -> None:
    op.drop_index("ix_work_partners_inst_count", table_name="work_partners")
    op.drop_column("work_partners", "partner_count")
    op.drop_column("work_partners", "home_corresponding")

    op.execute("DROP INDEX IF EXISTS ix_partner_institutions_search_trgm")
    op.drop_index("ix_partner_institutions_rollup_ror", table_name="partner_institutions")
    op.drop_column("partner_institutions", "rollup_ror")
    op.drop_column("partner_institutions", "acronyms")
    op.drop_column("partner_institutions", "search_text")
