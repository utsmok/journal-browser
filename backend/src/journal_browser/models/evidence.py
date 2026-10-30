from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _tstamp

# ── OpenAPC cost evidence ───────────────────────────────────────────────────


class ApcEvidence(Base):
    """Per-article APC/TA cost row (OpenAPC). Twente + NL deal institutions."""

    __tablename__ = "apc_evidence"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    doi: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    period: Mapped[int | None] = mapped_column(Integer, nullable=True)
    euro: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    is_hybrid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    agreement: Mapped[str | None] = mapped_column(Text, nullable=True)
    group_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    issn_l: Mapped[str | None] = mapped_column(String(9), nullable=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="openapc")
    source_record_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("source_records.id"), nullable=True
    )

    __table_args__ = (Index("ix_apc_evidence_issn_period", "issn_l", "period"),)


class JournalApcAggregate(Base):
    """Journal-level cost evidence: ISSN-L x period aggregates of OpenAPC rows."""

    __tablename__ = "journal_apc_aggregates"

    issn_l: Mapped[str] = mapped_column(String(9), primary_key=True)
    period: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="openapc")
    article_count: Mapped[int] = mapped_column(Integer, nullable=False)
    euro_min: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    euro_max: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    euro_mean: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)


# ── Institution statistics (precomputed; 2020+ window) ─────────────────────


class InstitutionWorksStats(Base):
    __tablename__ = "institution_works_stats"

    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"), primary_key=True)
    # 'pure_canon' (works harvested from the institution's Pure) or
    # 'openalex_institution_filter' (OpenAlex works filter cross-check).
    source: Mapped[str] = mapped_column(Text, primary_key=True)
    issn_l: Mapped[str] = mapped_column(String(9), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    works_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    oa_gold: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    oa_hybrid: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    oa_green: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    oa_bronze: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    oa_diamond: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    oa_closed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    updated_at: Mapped[datetime] = _tstamp()


class InstitutionTrend(Base):
    """Institution-wide yearly totals (works per year + OA split)."""

    __tablename__ = "institution_trends"

    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    works_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    corresponding_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    oa_gold: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    oa_hybrid: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    oa_green: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    oa_bronze: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    oa_diamond: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    oa_closed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    updated_at: Mapped[datetime] = _tstamp()
