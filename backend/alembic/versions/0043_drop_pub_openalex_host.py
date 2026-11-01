"""publishers.openalex_host_organization: dead column, dropped.

Created by the initial schema but never written by any harvester (the
OpenAlex host-organization id lives in the source_records payloads the
publishers job reads; ut-metadata-era data never migrated it). 0 rows
carry a value on live. Reversible per repo convention.

Revision ID: 0043_drop_pub_openalex_host
Revises: 0042_pure_person_orgs
Create Date: 2026-11-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0043_drop_pub_openalex_host"
down_revision: Union[str, None] = "0042_pure_person_orgs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("publishers", "openalex_host_organization")


def downgrade() -> None:
    # Historical record restore: the column was always nullable and
    # unused, so recreating it empty is exact.
    op.add_column(
        "publishers",
        sa.Column("openalex_host_organization", sa.Text(), nullable=True),
    )
