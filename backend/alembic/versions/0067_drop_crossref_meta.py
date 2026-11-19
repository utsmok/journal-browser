"""Drop the dead journals.crossref_meta column.

Null on all 177,738 rows; no router, service, or job reads or writes it
(the Crossref work harvest feeds author-level enrichment instead). The
column was a placeholder for a journal-policies path that never
happened.

Downgrade re-adds the nullable JSONB column; it stays NULL, which is
exactly the state the data was in.

Revision ID: 0067_drop_crossref_meta
Revises: 0066_superseded_run_status
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0067_drop_crossref_meta"
down_revision: str | None = "0066_superseded_run_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("journals", "crossref_meta")


def downgrade() -> None:
    op.add_column(
        "journals",
        sa.Column("crossref_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
