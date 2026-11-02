"""Jisc Open Policy Finder schema: canon tables + journals enrichment columns.

Six normalized tables (PKs are the provider's own Sherpa/OpenDOAR ids, no
autoincrement) plus the nine nullable `journals` columns the normalizer
stamps (tri-state: NULL = never swept). No FK constraints: harvest order
independence, links ride as JSONB id lists.

Revision ID: 0046_jisc_policy
Revises: 0045_curation_resolved_reason
Create Date: 2026-11-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0046_jisc_policy"
down_revision = "0045_curation_resolved_reason"
branch_labels = None
depends_on = None


def jisc_columns() -> list[sa.Column]:
    return [
        sa.Column("jisc_in_opf", sa.Boolean(), nullable=True),
        sa.Column("jisc_oa_prohibited", sa.Boolean(), nullable=True),
        sa.Column("jisc_sherpa_id", sa.Integer(), nullable=True),
        sa.Column("jisc_allows_sa_submitted", sa.Boolean(), nullable=True),
        sa.Column("jisc_allows_sa_accepted", sa.Boolean(), nullable=True),
        sa.Column("jisc_allows_sa_published", sa.Boolean(), nullable=True),
        sa.Column("jisc_embargo_accepted_months", sa.Integer(), nullable=True),
        sa.Column("jisc_policy", JSONB(), nullable=True),
        sa.Column("jisc_harvested_at", sa.DateTime(timezone=True), nullable=True),
    ]


def int_pk(name: str) -> sa.Column:
    return sa.Column(name, sa.Integer(), primary_key=True, autoincrement=False)


def date_modified() -> sa.Column:
    return sa.Column("date_modified", sa.DateTime(timezone=True), nullable=True)


def harvested_at() -> sa.Column:
    return sa.Column(
        "harvested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )


TABLES = [
    (
        "jisc_publications",
        [
            int_pk("id"),
            sa.Column("title", sa.Text(), nullable=True),
            sa.Column("pub_type", sa.Text(), nullable=True),
            sa.Column("url", sa.Text(), nullable=True),
            sa.Column("listed_in_doaj", sa.Boolean(), nullable=True),
            sa.Column("issns", JSONB(), nullable=True),
            sa.Column("publisher_ids", JSONB(), nullable=True),
            sa.Column("policy_ids", JSONB(), nullable=True),
            sa.Column("issn_l", sa.String(9), nullable=True),
            date_modified(),
            harvested_at(),
        ],
    ),
    (
        "jisc_publishers",
        [
            int_pk("id"),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("url", sa.Text(), nullable=True),
            sa.Column("country", sa.String(2), nullable=True),
            sa.Column("ror", sa.Text(), nullable=True),
            sa.Column("publication_count", sa.Integer(), nullable=True),
            sa.Column("imprint_of_id", sa.Integer(), nullable=True),
            date_modified(),
            harvested_at(),
        ],
    ),
    (
        "jisc_policies",
        [
            int_pk("id"),
            sa.Column("publisher_id", sa.Integer(), nullable=True),
            sa.Column("open_access_prohibited", sa.Boolean(), nullable=True),
            sa.Column("internal_moniker", sa.Text(), nullable=True),
            sa.Column("urls", JSONB(), nullable=True),
            sa.Column("workflow_dates", JSONB(), nullable=True),
            sa.Column("permitted_oa", JSONB(), nullable=True),
            sa.Column("publication_count", sa.Integer(), nullable=True),
            date_modified(),
            harvested_at(),
        ],
    ),
    (
        "jisc_funders",
        [
            int_pk("id"),
            sa.Column("name", sa.Text(), nullable=True),
            sa.Column("country", sa.String(2), nullable=True),
            sa.Column("url", sa.Text(), nullable=True),
            sa.Column("identifiers", JSONB(), nullable=True),
            sa.Column("publications_policy", JSONB(), nullable=True),
            sa.Column("data_archiving_policy", JSONB(), nullable=True),
            date_modified(),
            harvested_at(),
        ],
    ),
    (
        "jisc_funder_groups",
        [
            int_pk("id"),
            sa.Column("name", sa.Text(), nullable=True),
            sa.Column("funders", JSONB(), nullable=True),
            date_modified(),
            harvested_at(),
        ],
    ),
    (
        "jisc_repositories",
        [
            int_pk("id"),
            sa.Column("name", sa.Text(), nullable=True),
            sa.Column("type", sa.Text(), nullable=True),
            sa.Column("url", sa.Text(), nullable=True),
            sa.Column("oai_url", sa.Text(), nullable=True),
            sa.Column("software", sa.Text(), nullable=True),
            sa.Column("content_subjects", JSONB(), nullable=True),
            sa.Column("content_types", JSONB(), nullable=True),
            sa.Column("full_text_record_count", sa.Integer(), nullable=True),
            sa.Column("metadata_record_count", sa.Integer(), nullable=True),
            date_modified(),
            harvested_at(),
        ],
    ),
]


def upgrade() -> None:
    for name, columns in TABLES:
        op.create_table(name, *columns)
    for column in jisc_columns():
        op.add_column("journals", column)


def downgrade() -> None:
    for column in jisc_columns():
        op.drop_column("journals", column.name)
    for name, _ in TABLES:
        op.drop_table(name)
