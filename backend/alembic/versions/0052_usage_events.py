"""Anonymous usage-event intake (page views, searches, client errors).

Revision ID: 0052_usage_events
Revises: 0051_funder_streams
Create Date: 2026-11-04
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import INET, JSONB, TIMESTAMP

revision = "0052_usage_events"
down_revision = "0051_funder_streams"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "ts", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("query", sa.Text(), nullable=True),
        sa.Column("results_count", sa.Integer(), nullable=True),
        sa.Column("search_scope", sa.Text(), nullable=True),
        sa.Column("filters", JSONB(), nullable=True),
        sa.Column("ref_type", sa.Text(), nullable=True),
        sa.Column("ref_id", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("status", sa.Integer(), nullable=True),
        sa.Column("referrer", sa.Text(), nullable=True),
        sa.Column("ip", INET(), nullable=True),
        sa.Column("country", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("tz", sa.Text(), nullable=True),
        sa.Column("locale", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "event_type IN ('page_view', 'search', 'error')", name="ck_usage_event_type"
        ),
        sa.CheckConstraint(
            "search_scope IN ('journals', 'funders', 'authors', 'publishers', 'orgunits')",
            name="ck_usage_search_scope",
        ),
        sa.CheckConstraint(
            "ref_type IN ('journal', 'funder', 'author', 'orgunit', 'publisher')",
            name="ck_usage_ref_type",
        ),
        sa.CheckConstraint("(ref_type IS NULL) = (ref_id IS NULL)", name="ck_usage_ref_pair"),
        sa.CheckConstraint(
            "source IN ('js_error', 'unhandled_rejection', 'api_status')", name="ck_usage_source"
        ),
    )
    op.create_index("ix_usage_events_ts", "usage_events", ["ts"])
    op.create_index("ix_usage_events_type_ts", "usage_events", ["event_type", "ts"])
    op.create_index("ix_usage_events_session", "usage_events", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_usage_events_session", table_name="usage_events")
    op.drop_index("ix_usage_events_type_ts", table_name="usage_events")
    op.drop_index("ix_usage_events_ts", table_name="usage_events")
    op.drop_table("usage_events")
