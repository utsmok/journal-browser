"""status_changes: append-only audit of admin status flips.

Review surfaces (author identities, work identities, feedback triage)
previously left only updated_at behind, so an admin decision had no
history. Every actual transition now appends a row here; no-op writes
record nothing.

Revision ID: 0044_status_change_log
Revises: 0043_drop_pub_openalex_host
Create Date: 2026-11-01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0044_status_change_log"
down_revision = "0043_drop_pub_openalex_host"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "status_changes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("table_name", sa.Text(), nullable=False),
        sa.Column("row_key", JSONB(), nullable=False),
        sa.Column("field", sa.Text(), nullable=False, server_default="status"),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.Text(), nullable=True),
        sa.Column("changed_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_status_changes_table_time",
        "status_changes",
        ["table_name", "changed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_status_changes_table_time", table_name="status_changes")
    op.drop_table("status_changes")
