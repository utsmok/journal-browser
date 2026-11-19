"""Per-work funders-check stamp so zero-award works leave the sweep.

The work-funders harvest re-fetched every work that carries no
work_funders row on every nightly run: "fresh" was derived from the rows'
harvested_at, and works OpenAlex reports without awards never grow a row.
works.funders_checked_at records when a work's awards were last fetched;
the harvest gates its candidate query on it (TTL from the job's existing
--ttl-days / JB_WORK_FUNDERS_TTL_DAYS setting) and stamps it per fetched
chunk, zero-award works included. Backfill is unnecessary: unstamped
works are simply eligible for one more sweep, after which every work
carries the stamp.

Downgrade drops the column; the next run re-checks every work once.

Revision ID: 0069_work_funders_checked_at
Revises: 0068_openalex_export_columns
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0069_work_funders_checked_at"
down_revision: str | None = "0068_openalex_export_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "works", sa.Column("funders_checked_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("works", "funders_checked_at")
