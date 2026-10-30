from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Computed,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Journal(Base):
    """Normalized OpenAlex source. Raw payload lives in source_records."""

    __tablename__ = "journals"

    issn_l: Mapped[str] = mapped_column(String(9), primary_key=True)
    openalex_id: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    publisher_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Canonical publisher display name (OpenAlex lineage root, resolved by
    # jobs/harvest_publishers.py); NULL/empty groups by publisher_name.
    publisher_canonical: Mapped[str | None] = mapped_column(Text, nullable=True)
    publisher_id: Mapped[int | None] = mapped_column(ForeignKey("publishers.id"), nullable=True)
    type: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_oa: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_in_doaj: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    homepage_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    country_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    issns: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    alternate_titles: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    topics: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    apc_prices: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    summary_stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    counts_by_year: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    works_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cited_by_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Corpus cutoff (owner decision 2026-10-23, superseding decision 12):
    # total works in the 2020+ window, derived at upsert time from
    # counts_by_year. Journals with <= 3 works are presentation-excluded.
    last_active_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    works_2020_plus: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    in_scimago: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Global denormalized search columns (institution-neutral), refreshed by
    # harvest.denorm; the per-institution state lives in journal_flags.
    latest_quartile: Mapped[str | None] = mapped_column(String(4), nullable=True)
    # Denormalized most recent known OpenAPC cost: the highest single
    # reported APC in the journal's newest period with cost evidence (not a
    # period mean), so the results table can sort on APC without a
    # correlated subquery per row (same pattern as latest_quartile);
    # refreshed by harvest.denorm.refresh_apcs.
    latest_apc_euro: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    # Modal non-green Work oa_status across the journal's most recent works
    # (harvest/journal_oa.py), sampled because OpenAlex marks the venue
    # is_oa without saying which OA color. bronze/closed/green mean "no OA
    # color observed"; oa_type falls back to deal/subscription for them.
    oa_status_observed: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # DOAJ journal-record canon (harvest/doaj.py): the authoritative OA-model
    # source. doaj_in_doaj is tri-state until a full DOAJ sweep stamps the
    # OA candidates that did not match; classification treats NULL as
    # "unknown", never as membership.
    doaj_in_doaj: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # DOAJ apc.has_apc: the venue's own charge declaration. True = charges
    # exist (gold evidence); False = diamond.
    doaj_has_apc: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    doaj_apc_max: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    doaj_apc_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    doaj_homepage_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    doaj_harvested_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    crossref_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    openaire_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    harvested_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    search_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_vector: Mapped[Any] = mapped_column(
        # Postgres generated columns reject subqueries, so the harvester
        # maintains search_text (title + alternate titles) and this vector
        # derives from it. Declared TSVECTOR explicitly: an untyped column
        # silently lands as varchar and every FTS op fails.
        TSVECTOR,
        Computed("to_tsvector('english', coalesce(search_text, ''))", persisted=True),
        nullable=True,
    )
    # 384-dim bge-small-en-v1.5 text embedding (cleaned title + topics + top
    # cited works), written only by jobs/embed_journals.py; powers the
    # embedding path of similar_journals (services/search.py).
    embedding: Mapped[Any] = mapped_column(Vector(384), nullable=True)


class ScimagojrMetric(Base):
    """SJR + quartile per ISSN-L x year, stored as published."""

    __tablename__ = "scimagojr_metrics"

    issn_l: Mapped[str] = mapped_column(String(9), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    sjr: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    best_quartile: Mapped[str | None] = mapped_column(Text, nullable=True)
    h_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extras: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


# ── Per-institution journal state + works corpus ────────────────────────────


class JournalFlags(Base):
    """Per-institution denormalized journal state for search and facets.

    Fully materialized (one row per journal per hosted institution) so the
    search path stays a simple indexed join. Refreshed wholesale by
    harvest.denorm after stats / deal-register changes.
    """

    __tablename__ = "journal_flags"

    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), primary_key=True
    )
    issn_l: Mapped[str] = mapped_column(
        String(9), ForeignKey("journals.issn_l", ondelete="CASCADE"), primary_key=True
    )
    # The institution's works in this journal (pure_canon primary), the
    # sort key for institution_works and the has_works facet.
    works_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # Effective deal coverage for this institution (override-aware).
    deal_covered: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # Journal's own works inside THIS institution's data window; the >3
    # corpus cutoff reads it (owner decision 2026-10-23).
    works_window_plus: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    # Presentation-excluded for this institution (proceedings-like title,
    # no deal coverage, no institution works); decision 16 in
    # docs/decisions.md.
    browse_excluded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
