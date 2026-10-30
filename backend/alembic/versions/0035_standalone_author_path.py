"""Standalone author path: Pure CERIF entities + OpenAlex works store.

The author pages' DSN replacements (docs/standalone-author-path.md):
pure_orgs/pure_org_parents (org tree), pure_persons (roster canon),
work_pure_authors (pure-side authorship edges with work affiliations),
openalex_works (projection of the institution-scoped OpenAlex works
sweep), and author_identities (the identity review surface —
confirmed/candidate/rejected, candidates never auto-promote).

Revision history: down_revision 0034.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision: str = "0035_standalone_author_path"
down_revision: str | None = "0034_author_openalex_ids"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pure_orgs",
        sa.Column(
            "institution_id",
            sa.Integer(),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("uuid", pg.TEXT(), primary_key=True),
        sa.Column("name", pg.TEXT(), nullable=False),
        sa.Column("org_type", pg.TEXT(), nullable=True),
        sa.Column("identifiers", pg.JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column(
            "updated_at",
            pg.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_table(
        "pure_org_parents",
        sa.Column(
            "institution_id",
            sa.Integer(),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("org_uuid", pg.TEXT(), primary_key=True),
        sa.Column("parent_uuid", pg.TEXT(), primary_key=True),
        sa.Column("parent_name", pg.TEXT(), nullable=True),
        sa.ForeignKeyConstraint(
            ["institution_id", "org_uuid"],
            ["pure_orgs.institution_id", "pure_orgs.uuid"],
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "pure_persons",
        sa.Column(
            "institution_id",
            sa.Integer(),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("uuid", pg.TEXT(), primary_key=True),
        sa.Column("orcid", pg.TEXT(), nullable=True),
        sa.Column("name", pg.TEXT(), nullable=True),
        sa.Column("payload", pg.JSONB(), nullable=False),
        sa.Column(
            "updated_at",
            pg.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_pure_persons_inst_orcid",
        "pure_persons",
        ["institution_id", "orcid"],
        postgresql_where=sa.text("orcid IS NOT NULL"),
    )
    op.create_table(
        "work_pure_authors",
        sa.Column(
            "institution_id",
            sa.Integer(),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("work_pure_uuid", pg.TEXT(), primary_key=True),
        sa.Column("person_uuid", pg.TEXT(), primary_key=True),
        sa.Column("position", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("first_names", pg.TEXT(), nullable=True),
        sa.Column("family_names", pg.TEXT(), nullable=True),
        sa.Column("affiliations", pg.JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.ForeignKeyConstraint(
            ["institution_id", "work_pure_uuid"],
            ["works.institution_id", "works.pure_uuid"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_work_pure_authors_inst_person",
        "work_pure_authors",
        ["institution_id", "person_uuid"],
    )
    op.create_table(
        "openalex_works",
        sa.Column(
            "institution_id",
            sa.Integer(),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("w_id", pg.TEXT(), primary_key=True),
        sa.Column("doi_normalized", pg.TEXT(), nullable=True),
        sa.Column("title", pg.TEXT(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("work_type", pg.TEXT(), nullable=True),
        sa.Column("oa_status", pg.TEXT(), nullable=True),
        sa.Column("venue_issn_l", pg.TEXT(), nullable=True),
        sa.Column("venue_name", pg.TEXT(), nullable=True),
        sa.Column("authorships", pg.JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("cited_by_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fwci", sa.Float(), nullable=True),
        sa.Column(
            "is_retracted", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("source", pg.TEXT(), nullable=False, server_default="works_stats"),
        sa.Column(
            "updated_at",
            pg.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "oa_status IN ('gold', 'hybrid', 'green', 'bronze', 'diamond', 'closed')",
            name="ck_openalex_works_oa_status",
        ),
    )
    # Non-unique on purpose: merged OpenAlex profiles can carry one
    # publication under two W-ids with the same DOI; serving dedupes by DOI.
    op.create_index(
        "ix_openalex_works_inst_doi",
        "openalex_works",
        ["institution_id", "doi_normalized"],
        postgresql_where=sa.text("doi_normalized IS NOT NULL"),
    )
    op.create_index(
        "ix_openalex_works_inst_issn",
        "openalex_works",
        ["institution_id", "venue_issn_l"],
        postgresql_where=sa.text("venue_issn_l IS NOT NULL"),
    )
    op.create_index(
        "ix_openalex_works_inst_year",
        "openalex_works",
        ["institution_id", "year"],
        postgresql_where=sa.text("year IS NOT NULL"),
    )
    op.create_table(
        "author_identities",
        sa.Column(
            "institution_id",
            sa.Integer(),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("author_pure_uuid", pg.TEXT(), primary_key=True),
        sa.Column("source", pg.TEXT(), primary_key=True, server_default="openalex"),
        sa.Column("external_id", pg.TEXT(), primary_key=True),
        sa.Column("status", pg.TEXT(), nullable=False, server_default="candidate"),
        sa.Column("method", pg.TEXT(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("n_works", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "orcid_corroborated", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("evidence", pg.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "updated_at",
            pg.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('confirmed', 'candidate', 'rejected')",
            name="ck_author_identities_status",
        ),
        sa.CheckConstraint(
            "source IN ('openalex')",
            name="ck_author_identities_source",
        ),
        # Soft-keyed on purpose: authors is full-replaced per ingest, and
        # identities are durable review state that must survive it.
    )
    op.create_index(
        "ix_author_identities_inst_author",
        "author_identities",
        ["institution_id", "author_pure_uuid"],
    )
    op.create_index(
        "ix_author_identities_inst_status",
        "author_identities",
        ["institution_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_author_identities_inst_status", table_name="author_identities")
    op.drop_index("ix_author_identities_inst_author", table_name="author_identities")
    op.drop_table("author_identities")
    op.drop_index("ix_openalex_works_inst_year", table_name="openalex_works")
    op.drop_index("ix_openalex_works_inst_issn", table_name="openalex_works")
    op.drop_index("ix_openalex_works_inst_doi", table_name="openalex_works")
    op.drop_table("openalex_works")
    op.drop_index("ix_work_pure_authors_inst_person", table_name="work_pure_authors")
    op.drop_table("work_pure_authors")
    op.drop_index("ix_pure_persons_inst_orcid", table_name="pure_persons")
    op.drop_table("pure_persons")
    op.drop_table("pure_org_parents")
    op.drop_table("pure_orgs")
