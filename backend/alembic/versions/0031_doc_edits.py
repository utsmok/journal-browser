"""Editable doc blocks: admin overrides for the served markdown docs.

Revision ID: 0031_doc_edits
Revises: 0030_doaj_limitations
Create Date: 2026-10-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0031_doc_edits"
down_revision: Union[str, None] = "0030_doaj_limitations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "doc_edits",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("doc_slug", sa.Text(), nullable=False),
        sa.Column("block_key", sa.Text(), nullable=False),
        sa.Column("original_hash", sa.Text(), nullable=False),
        sa.Column("replacement", sa.Text(), nullable=False),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")
        ),
        sa.UniqueConstraint("doc_slug", "block_key", name="uq_doc_edits_block"),
    )


def downgrade() -> None:
    op.drop_table("doc_edits")
