from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _tstamp


class Work(Base):
    """Canonical institution work harvested from its Pure via OAI-PMH."""

    __tablename__ = "works"

    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id"), primary_key=True
    )
    pure_uuid: Mapped[str] = mapped_column(Text, primary_key=True)
    doi_normalized: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    norm_title: Mapped[str] = mapped_column(Text, nullable=False)
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    work_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    publisher: Mapped[str | None] = mapped_column(Text, nullable=True)
    cerif_issn: Mapped[str | None] = mapped_column(Text, nullable=True)
    oa_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    journal_issn_l: Mapped[str | None] = mapped_column(
        Text, ForeignKey("journals.issn_l"), nullable=True
    )
    first_seen_run: Mapped[int] = mapped_column(ForeignKey("harvest_runs.id"), nullable=False)
    last_seen_run: Mapped[int] = mapped_column(ForeignKey("harvest_runs.id"), nullable=False)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = _tstamp()

    __table_args__ = (
        CheckConstraint(
            "oa_status IN ('gold', 'hybrid', 'green', 'bronze', 'diamond', 'closed')",
            name="ck_works_oa_status",
        ),
        # Pure occasionally carries one publication under two uuids; the
        # twin keeps the DOI and the other row stays NULL-doi.
        Index(
            "uq_works_inst_doi",
            "institution_id",
            "doi_normalized",
            unique=True,
            postgresql_where=text("doi_normalized IS NOT NULL"),
        ),
        Index(
            "ix_works_inst_journal",
            "institution_id",
            "journal_issn_l",
            postgresql_where=text("journal_issn_l IS NOT NULL"),
        ),
    )


# ON CONFLICT targets live as literals in harvest code; this constant is
# the single name the model, the migration, and those statements share.
WORK_IDENTITY_UQ = "uq_work_identity_source"


class WorkIdentity(Base):
    """Cross-source identity link between an external record and a work.

    matched_by: 'doi' (auto-confirm), 'trgm:<threshold>[+v][+a]' (fuzzy,
    curation candidates), or 'verbatim' (shared source string).
    """

    __tablename__ = "work_identity"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id"), nullable=False
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_pk: Mapped[str] = mapped_column(Text, nullable=False)
    work_id: Mapped[str] = mapped_column(Text, nullable=False)
    matched_by: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="candidate")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _tstamp()
    updated_at: Mapped[datetime] = _tstamp()

    __table_args__ = (
        CheckConstraint(
            "status IN ('confirmed', 'missing', 'candidate')",
            name="ck_work_identity_status",
        ),
        CheckConstraint(
            "matched_by ~ '^(doi|verbatim|trgm:.+)$'",
            name="ck_work_identity_matched_by",
        ),
        ForeignKeyConstraint(
            ["institution_id", "work_id"],
            ["works.institution_id", "works.pure_uuid"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "institution_id", "source", "source_pk", name=WORK_IDENTITY_UQ
        ),
        Index("ix_work_identity_inst_work", "institution_id", "work_id"),
    )
