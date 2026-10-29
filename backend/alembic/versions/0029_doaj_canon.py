"""DOAJ canon harvest: journal-level OA-model truth on journals.

Revision ID: 0029_doaj_canon
Revises: 0028_feedback_items
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0029_doaj_canon"
down_revision = "0028_feedback_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in (
        sa.Column("doaj_in_doaj", sa.Boolean(), nullable=True),
        sa.Column("doaj_has_apc", sa.Boolean(), nullable=True),
        sa.Column("doaj_apc_max", sa.Numeric(), nullable=True),
        sa.Column("doaj_apc_currency", sa.String(length=3), nullable=True),
        sa.Column("doaj_homepage_url", sa.Text(), nullable=True),
        sa.Column("doaj_harvested_at", sa.TIMESTAMP(timezone=True), nullable=True),
    ):
        op.add_column("journals", column)


def downgrade() -> None:
    for column in (
        "doaj_harvested_at",
        "doaj_homepage_url",
        "doaj_apc_currency",
        "doaj_apc_max",
        "doaj_has_apc",
        "doaj_in_doaj",
    ):
        op.drop_column("journals", column)
