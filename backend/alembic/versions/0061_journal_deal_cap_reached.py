"""journal_flags.deal_cap_reached: every covering deal's APC cap used up.

Revision ID: 0061_journal_deal_cap_reached
Revises: 0060_deal_cap_usage
Create Date: 2026-11-11

Denormalized twin of deals.cap_usage (0060) for search rows: true iff the
journal's effective covering current deals are ALL cap-reached (latest
cap_usage entry with used >= total). Refreshed wholesale by
harvest.denorm.DEAL_CAP_REACHED_SQL alongside deal_covered.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0061_journal_deal_cap_reached"
down_revision: Union[str, None] = "0060_deal_cap_usage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "journal_flags",
        sa.Column(
            "deal_cap_reached", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )


def downgrade() -> None:
    op.drop_column("journal_flags", "deal_cap_reached")
