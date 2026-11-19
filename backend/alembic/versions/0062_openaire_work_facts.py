"""openaire_work_facts store + journal_flags.openaire_diamond.

Revision ID: 0062_openaire_work_facts
Revises: 0061_journal_deal_cap_reached
Create Date: 2026-11-13

Derived per-work OpenAIRE facts (one row per confirmed openaire identity,
rebuilt by harvest.openaire_facts): usage counts, diamond flag, OA color,
license, fulltext url, embargo, FOS subjects, projects. The journal_flags
flag stamps "some work of this journal is diamond per OpenAIRE" alongside
deal_covered (harvest.denorm.OPENAIRE_DIAMOND_SQL).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0062_openaire_work_facts"
down_revision: Union[str, None] = "0061_journal_deal_cap_reached"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "openaire_work_facts",
        sa.Column("institution_id", sa.Integer(), nullable=False),
        sa.Column("pure_uuid", sa.Text(), nullable=False),
        sa.Column("source_pk", sa.Text(), nullable=False),
        sa.Column("views", sa.Integer(), nullable=True),
        sa.Column("downloads", sa.Integer(), nullable=True),
        sa.Column(
            "diamond", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("oa_color", sa.Text(), nullable=True),
        sa.Column("license", sa.Text(), nullable=True),
        sa.Column("oa_url", sa.Text(), nullable=True),
        sa.Column("embargo_end", sa.Date(), nullable=True),
        sa.Column("fos", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column(
            "projects", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("institution_id", "pure_uuid"),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["institution_id", "pure_uuid"],
            ["works.institution_id", "works.pure_uuid"],
            ondelete="CASCADE",
        ),
    )
    op.add_column(
        "journal_flags",
        sa.Column(
            "openaire_diamond", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )


def downgrade() -> None:
    op.drop_column("journal_flags", "openaire_diamond")
    op.drop_table("openaire_work_facts")
