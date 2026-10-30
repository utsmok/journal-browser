from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _tstamp


class Deal(Base):
    __tablename__ = "deals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    publisher_id: Mapped[int | None] = mapped_column(ForeignKey("publishers.id"), nullable=True)
    esac_id: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    consortium: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="current")
    start_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    corresponding_authors_only: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    conditions_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    workflow_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    article_types_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    cap_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    cap_numbers: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    contract_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    openaccess_nl_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    jct_data_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    per_year_oa_counts: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    provenance: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    # Register links from the owner-reviewed snapshot: [{url, text, category}].
    links: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    needs_curation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    needs_curation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_reviewed: Mapped[str | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = _tstamp()

    __table_args__ = (
        CheckConstraint("status IN ('current', 'archive')", name="ck_deals_status"),
        CheckConstraint(
            "needs_curation = true OR needs_curation_reason IS NULL",
            name="ck_deals_curation_reason",
        ),
        Index("ix_deals_publisher", "publisher_id", "status"),
    )


class DealJournal(Base):
    """Deal journal coverage. Rows with institution_id NULL are the shared
    sheet coverage (ESAC/JCT/openaccess.nl); institution-scoped rows are
    per-institution overrides that replace the shared list for institutions
    whose deal_institutions.journal_override is set."""

    __tablename__ = "deal_journals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), nullable=False)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), nullable=True)
    # Normalized source ISSN (print or online, as the deal list publishes).
    # issn_l stays NULL until the issn_map sweep resolves it; then
    # needs_curation marks anything that never resolved.
    issn: Mapped[str] = mapped_column(String(9), nullable=False)
    issn_l: Mapped[str | None] = mapped_column(String(9), nullable=True, index=True)
    journal_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    needs_curation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    needs_curation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Admin-removed from the deal (PUT /admin/deals/{id}/journals). The row
    # is kept so the JCT upsert cannot resurrect it; hidden from coverage.
    excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    __table_args__ = (
        CheckConstraint(
            "source IN ('jct', 'manual', 'publisher-pattern')",
            name="ck_deal_journals_source",
        ),
        CheckConstraint(
            "needs_curation = true OR needs_curation_reason IS NULL",
            name="ck_deal_journals_curation_reason",
        ),
        # Partial uniques instead of one NULLS NOT DISTINCT key: ON CONFLICT
        # can target each partial index explicitly.
        Index(
            "uq_deal_journals_shared",
            "deal_id",
            "issn",
            unique=True,
            postgresql_where=text("institution_id IS NULL"),
        ),
        Index(
            "uq_deal_journals_scoped",
            "deal_id",
            "issn",
            "institution_id",
            unique=True,
            postgresql_where=text("institution_id IS NOT NULL"),
        ),
    )


class DealInstitution(Base):
    """Deal ↔ institution partnership relation. A missing row means
    non-participation; a shared deal is never deleted for it."""

    __tablename__ = "deal_institutions"

    deal_id: Mapped[int] = mapped_column(
        ForeignKey("deals.id", ondelete="CASCADE"), primary_key=True
    )
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"), primary_key=True)
    # 'named' (institution listed in the deal text) or 'consortium'
    # (national deal, no member enumeration); NULL = unassessed.
    participation: Mapped[str | None] = mapped_column(Text, nullable=True)
    participation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # When true, this institution's coverage is the institution-scoped
    # deal_journals rows instead of the shared sheet list.
    journal_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    first_seen: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "participation IN ('named', 'consortium')",
            name="ck_deal_institutions_participation",
        ),
    )


# ── Journals ────────────────────────────────────────────────────────────────
