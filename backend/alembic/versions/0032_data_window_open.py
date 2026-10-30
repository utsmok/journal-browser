"""Open-ended data window: NULL instead of the 0 = open sentinel.

Revision ID: 0032_data_window_open
Revises: 0031_doc_edits
Create Date: 2026-10-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0032_data_window_open"
down_revision: Union[str, None] = "0031_doc_edits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "institutions",
        "data_window_end",
        existing_type=sa.Integer(),
        nullable=True,
        server_default=None,
    )
    op.execute("UPDATE institutions SET data_window_end = NULL WHERE data_window_end = 0")


def downgrade() -> None:
    op.execute("UPDATE institutions SET data_window_end = 0 WHERE data_window_end IS NULL")
    op.alter_column(
        "institutions",
        "data_window_end",
        existing_type=sa.Integer(),
        nullable=False,
        server_default=sa.text("0"),
    )
