"""Funder canon link table: jisc_funders -> OpenAlex/OpenAIRE twin rows.

Revision ID: 0050_funder_links
Revises: 0049_add_work_funders
Create Date: 2026-11-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TIMESTAMP

revision = "0050_funder_links"
down_revision = "0049_add_work_funders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "funder_links",
        sa.Column("funder_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),  # 'openalex' | 'openaire'
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("via", sa.Text(), nullable=False),  # 'ror' | 'fundref'
        sa.Column(
            "updated_at",
            TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["funder_id"], ["jisc_funders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("funder_id", "source", "source_id"),
    )
    op.create_index("ix_funder_links_source", "funder_links", ["source", "source_id"])
    # Backfill from the current ror/fundref columns; a jisc funder may link
    # several OpenAlex twins (ror twin + fundref twin), so insert both rules.
    op.execute(
        """
        INSERT INTO funder_links (funder_id, source, source_id, via)
        SELECT j.id, 'openalex', o.openalex_id, 'ror'
        FROM jisc_funders j JOIN openalex_funders o ON o.ror = j.ror
        WHERE j.ror IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO funder_links (funder_id, source, source_id, via)
        SELECT j.id, 'openalex', o.openalex_id, 'fundref'
        FROM jisc_funders j JOIN openalex_funders o ON o.fundref = j.fundref
        WHERE j.fundref IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO funder_links (funder_id, source, source_id, via)
        SELECT j.id, 'openaire', a.openaire_id, 'ror'
        FROM jisc_funders j JOIN openaire_funders a ON a.ror = j.ror
        WHERE j.ror IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("funder_links")
