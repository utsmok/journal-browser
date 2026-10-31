"""pure_person_orgs: portal person→org bindings (relay-harvested
profiles listings).

The Pure portal's public HTML persons listings carry every current staff
member's organisation relations (org, role) without the 50-person RSS
cap. Bindings land here as gap-fill evidence only: the derive pipeline
consults them through dedicated portal arms (augment_faculty /
augment_institute / the portal research-group fill) that run after
native CERIF resolution — native results, the roster, and ROR
confirmation are untouched. The table is wholly portal-derived (the
bind job full-replaces it per institution), so the migration only
creates the container.

Revision ID: 0042_pure_person_orgs
Revises: 0041_authors_institute
Create Date: 2026-10-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0042_pure_person_orgs"
down_revision: Union[str, None] = "0041_authors_institute"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pure_person_orgs",
        sa.Column("institution_id", sa.Integer(), nullable=False),
        sa.Column("person_uuid", sa.Text(), nullable=False),
        sa.Column("org_uuid", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("portal_person_slug", sa.Text(), nullable=False),
        sa.Column("portal_org_slug", sa.Text(), nullable=False),
        sa.Column("listing_kinds", JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.ForeignKeyConstraint(
            ["institution_id", "person_uuid"],
            ["pure_persons.institution_id", "pure_persons.uuid"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id", "org_uuid"],
            ["pure_orgs.institution_id", "pure_orgs.uuid"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("institution_id", "person_uuid", "org_uuid"),
    )


def downgrade() -> None:
    op.drop_table("pure_person_orgs")
