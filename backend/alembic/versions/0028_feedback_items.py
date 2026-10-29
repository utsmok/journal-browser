"""In-app user feedback (public intake + admin triage).

Revision ID: 0028_feedback_items
Revises: 0027_oa_status_observed
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0028_feedback_items"
down_revision = "0027_oa_status_observed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feedback_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="todo"),
        sa.Column("priority", sa.Text(), nullable=False, server_default="normal"),
        sa.Column("page_url", sa.Text(), nullable=True),
        sa.Column("page_data", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")
        ),
        sa.CheckConstraint(
            "status IN ('todo', 'in_progress', 'done', 'wontfix')",
            name="ck_feedback_status",
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'critical')",
            name="ck_feedback_priority",
        ),
    )


def downgrade() -> None:
    op.drop_table("feedback_items")
