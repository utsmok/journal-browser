"""deals.cap_usage: admin-entered publisher APC cap usage.

Revision ID: 0060_deal_cap_usage
Revises: 0059_openalex_work_authors
Create Date: 2026-11-11

Library email updates record, per contract year, how many APCs a deal's
cap allows and how many are used; the frontend derives "cap reached" from
used >= total. Admin-owned like links: neither harvester lists the column
in its _DEAL_FIELDS, so scraped values can never overwrite the numbers a
librarian entered by hand.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0060_deal_cap_usage"
down_revision: Union[str, None] = "0059_openalex_work_authors"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("deals", sa.Column("cap_usage", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("deals", "cap_usage")
