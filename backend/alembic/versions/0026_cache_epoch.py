"""Cache epoch: one row every harvest bump, invalidating in-process caches.

Revision ID: 0026_cache_epoch
Revises: 0025_publisher_canonical
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0026_cache_epoch"
down_revision = "0025_publisher_canonical"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cache_epoch",
        sa.Column("id", pg.SMALLINT(), primary_key=True),
        sa.Column(
            "bumped_at",
            pg.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("id = 1", name="cache_epoch_single_row"),
    )
    op.execute("INSERT INTO cache_epoch (id) VALUES (1)")


def downgrade() -> None:
    op.drop_table("cache_epoch")
