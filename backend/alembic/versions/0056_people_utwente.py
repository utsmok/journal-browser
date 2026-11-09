"""people.utwente.nl profile tables + the author_identities 'people' source.

people_utwente_persons stores one harvest outcome per attempted author
(matched / candidate / missed, see models.people), keyed by the author's
pure uuid; people_utwente_person_orgs holds the page's orgs resolved
onto pure_orgs as gap-fill evidence (the pure_person_orgs pattern).
The identity cascade can now record people-pages name matches as
source='people' candidate rows for admin review.

Revision ID: 0056_people_utwente
Revises: 0055_embeddings_state_backfill
Create Date: 2026-11-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0056_people_utwente"
down_revision: Union[str, None] = "0055_embeddings_state_backfill"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_IDENTITY_SOURCE_OLD = "source IN ('openalex', 'openaire')"
_IDENTITY_SOURCE_NEW = "source IN ('openalex', 'openaire', 'people')"


def upgrade() -> None:
    op.create_table(
        "people_utwente_persons",
        sa.Column("institution_id", sa.Integer(), nullable=False),
        sa.Column("person_uuid", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="missed"),
        sa.Column("slug", sa.Text(), nullable=True),
        sa.Column("canonical_name", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("orgs", JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("faculty_abbr", sa.Text(), nullable=True),
        sa.Column("portal_person_url", sa.Text(), nullable=True),
        sa.Column("photo_url", sa.Text(), nullable=True),
        sa.Column("photo_media_type", sa.Text(), nullable=True),
        sa.Column("photo_bytes", sa.LargeBinary(), nullable=True),
        sa.Column("match_method", sa.Text(), nullable=True),
        sa.Column("match_confidence", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["institution_id", "person_uuid"],
            ["pure_persons.institution_id", "pure_persons.uuid"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("institution_id", "person_uuid"),
        sa.CheckConstraint(
            "status IN ('matched', 'candidate', 'missed')",
            name="ck_people_utwente_persons_status",
        ),
    )
    op.create_index(
        "ux_people_utwente_persons_inst_slug",
        "people_utwente_persons",
        ["institution_id", "slug"],
        unique=True,
        postgresql_where=sa.text("slug IS NOT NULL"),
    )

    op.create_table(
        "people_utwente_person_orgs",
        sa.Column("institution_id", sa.Integer(), nullable=False),
        sa.Column("person_uuid", sa.Text(), nullable=False),
        sa.Column("org_uuid", sa.Text(), nullable=False),
        sa.Column("people_slug", sa.Text(), nullable=False),
        sa.Column("org_abbr", sa.Text(), nullable=True),
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

    with op.batch_alter_table("author_identities") as batch:
        batch.drop_constraint("ck_author_identities_source", type_="check")
        batch.create_check_constraint("ck_author_identities_source", _IDENTITY_SOURCE_NEW)


def downgrade() -> None:
    with op.batch_alter_table("author_identities") as batch:
        batch.drop_constraint("ck_author_identities_source", type_="check")
        batch.create_check_constraint("ck_author_identities_source", _IDENTITY_SOURCE_OLD)
    op.drop_table("people_utwente_person_orgs")
    op.drop_index("ux_people_utwente_persons_inst_slug", table_name="people_utwente_persons")
    op.drop_table("people_utwente_persons")
