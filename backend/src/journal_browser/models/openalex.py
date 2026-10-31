"""OpenAlex works store + author identity review rows.

openalex_works is the normalized projection of the institution-scoped
OpenAlex works sweep (works_stats source_records) plus the budget-capped
per-author enrichment; it replaces the DSN's works-side features (journal
works tab, openalex-only merge, authorship edges). author_identities is
the review surface of the identity cascade: candidates never silently
become facts.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _tstamp


class OpenalexWork(Base):
    """One OpenAlex work of the institution's population.

    authorships is the compact form [{a: bare A-id, n: display name,
    o: bare orcid}] — enough for identity resolution and the authorship
    edges without re-fetching. Full-replace per institution at rebuild;
    the same publication under two W-ids is tolerated (latest wins).
    """

    __tablename__ = "openalex_works"

    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), primary_key=True
    )
    w_id: Mapped[str] = mapped_column(Text, primary_key=True)
    doi_normalized: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    work_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    oa_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    venue_issn_l: Mapped[str | None] = mapped_column(Text, nullable=True)
    venue_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    authorships: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'")
    )
    cited_by_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    fwci: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_retracted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # Provenance tag of the feeding harvest (works_stats / author:<n>).
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="works_stats")
    updated_at: Mapped[datetime] = _tstamp()

    __table_args__ = (
        CheckConstraint(
            "oa_status IN ('gold', 'hybrid', 'green', 'bronze', 'diamond', 'closed')",
            name="ck_openalex_works_oa_status",
        ),
        # Non-unique on purpose: merged OpenAlex profiles can carry one
        # publication under two W-ids with the same DOI; the serving paths
        # dedupe by DOI. The PK (institution_id, w_id) keeps rows distinct.
        Index(
            "ix_openalex_works_inst_doi",
            "institution_id",
            "doi_normalized",
            postgresql_where=text("doi_normalized IS NOT NULL"),
        ),
        Index(
            "ix_openalex_works_inst_issn",
            "institution_id",
            "venue_issn_l",
            postgresql_where=text("venue_issn_l IS NOT NULL"),
        ),
        Index(
            "ix_openalex_works_inst_year",
            "institution_id",
            "year",
            postgresql_where=text("year IS NOT NULL"),
        ),
    )


class AuthorIdentity(Base):
    """One external identity proposal/decision for a local author.

    status: 'confirmed' (orcid-exact, corroborated, or admin-promoted),
    'candidate' (ambiguous or weakest-rung — review needed, never
    auto-promoted), 'rejected' (admin-decided, sticky across re-runs).
    Soft-keyed on purpose: the authors table is full-replaced per ingest,
    and identities are durable state that must survive it. The additive
    openalex_ids build consults this table: confirmed ids enter
    authors.openalex_ids, rejected ids stay out.
    """

    __tablename__ = "author_identities"

    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), primary_key=True
    )
    author_pure_uuid: Mapped[str] = mapped_column(Text, primary_key=True)
    source: Mapped[str] = mapped_column(Text, primary_key=True, server_default="openalex")
    external_id: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="candidate")
    method: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    n_works: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    orcid_corroborated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    updated_at: Mapped[datetime] = _tstamp()

    __table_args__ = (
        CheckConstraint(
            "status IN ('confirmed', 'candidate', 'rejected')",
            name="ck_author_identities_status",
        ),
        CheckConstraint("source IN ('openalex', 'openaire')", name="ck_author_identities_source"),
        Index(
            "ix_author_identities_inst_author",
            "institution_id",
            "author_pure_uuid",
        ),
        Index(
            "ix_author_identities_inst_status",
            "institution_id",
            "status",
        ),
    )
