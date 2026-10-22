"""Database schema: harvest bookkeeping, landing store, and domain tables.

Landing store (ut-metadata pattern): verbatim payloads in `source_records`
(content-hash versioned, append-only) plus file-level raw copies in
`raw_files`. Normalized domain tables are rebuildable from the landing
store; `manual_overrides` survives every re-ingestion.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Float,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _tstamp() -> Mapped[datetime]:
    return mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


# ── Harvest bookkeeping + landing store ────────────────────────────────────


class HarvestRun(Base):
    __tablename__ = "harvest_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="running")
    started_at: Mapped[datetime] = _tstamp()
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    config_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    stats: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_harvest_runs_status",
        ),
    )


class HarvestState(Base):
    __tablename__ = "harvest_state"

    source: Mapped[str] = mapped_column(Text, primary_key=True)
    entity_type: Mapped[str] = mapped_column(Text, primary_key=True)
    filter_set: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    last_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("harvest_runs.id"), nullable=True
    )
    updated_at: Mapped[datetime] = _tstamp()


class SourceRecord(Base):
    """Verbatim payload version for one (source, entity, key)."""

    __tablename__ = "source_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_pk: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    harvested_at: Mapped[datetime] = _tstamp()
    harvest_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("harvest_runs.id"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "source",
            "entity_type",
            "source_pk",
            "content_hash",
            name="uq_source_records_version",
        ),
        Index(
            "ix_source_records_lookup",
            "source",
            "entity_type",
            "source_pk",
            text("harvested_at DESC"),
        ),
    )


class RawFile(Base):
    """File-level landing copy of a downloaded source artifact."""

    __tablename__ = "raw_files"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_pk: Mapped[str] = mapped_column(Text, nullable=False, default="")
    url: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fetched_at: Mapped[datetime] = _tstamp()
    harvest_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("harvest_runs.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "source", "entity_type", "source_pk", "content_hash", name="uq_raw_files_version"
        ),
    )


# ── Reference data ──────────────────────────────────────────────────────────


class Publisher(Base):
    __tablename__ = "publishers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    openalex_host_organization: Mapped[str | None] = mapped_column(Text, nullable=True)
    openaccess_nl_slug: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    aliases: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)


class Institution(Base):
    __tablename__ = "institutions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    ror: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    openalex_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_home: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class IssnMap(Base):
    """ISSN → ISSN-L resolution index, harvested from OpenAlex sources."""

    __tablename__ = "issn_map"

    issn: Mapped[str] = mapped_column(String(9), primary_key=True)
    issn_l: Mapped[str] = mapped_column(String(9), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = _tstamp()


# ── Deals (the core) ────────────────────────────────────────────────────────


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
    needs_curation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    needs_curation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_reviewed: Mapped[str | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = _tstamp()

    __table_args__ = (
        CheckConstraint("status IN ('current', 'archive')", name="ck_deals_status"),
        Index("ix_deals_publisher", "publisher_id", "status"),
    )


class DealJournal(Base):
    __tablename__ = "deal_journals"

    deal_id: Mapped[int] = mapped_column(
        ForeignKey("deals.id", ondelete="CASCADE"), primary_key=True
    )
    # Normalized source ISSN (print or online, as the deal list publishes).
    # issn_l stays NULL until the issn_map sweep resolves it; then
    # needs_curation marks anything that never resolved.
    issn: Mapped[str] = mapped_column(String(9), primary_key=True)
    issn_l: Mapped[str | None] = mapped_column(String(9), nullable=True, index=True)
    journal_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    needs_curation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    __table_args__ = (
        CheckConstraint("source IN ('jct', 'manual')", name="ck_deal_journals_source"),
    )


class DealInstitution(Base):
    __tablename__ = "deal_institutions"

    deal_id: Mapped[int] = mapped_column(
        ForeignKey("deals.id", ondelete="CASCADE"), primary_key=True
    )
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"), primary_key=True)
    first_seen: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen: Mapped[str | None] = mapped_column(Text, nullable=True)


# ── Journals ────────────────────────────────────────────────────────────────


class Journal(Base):
    """Normalized OpenAlex source. Raw payload lives in source_records."""

    __tablename__ = "journals"

    issn_l: Mapped[str] = mapped_column(String(9), primary_key=True)
    openalex_id: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    publisher_name: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    # Corpus quality bar (decisions.md #12): derived at upsert time,
    # zero extra API calls. last_active_year = latest counts_by_year
    # entry with works > 0; recent activity OR doaj OR scimago OR deal
    # coverage puts a journal in the default scope.
    last_active_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active_recently: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    in_scimago: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
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


class ScimagojrMetric(Base):
    """SJR + quartile per ISSN-L x year, stored as published."""

    __tablename__ = "scimagojr_metrics"

    issn_l: Mapped[str] = mapped_column(String(9), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    sjr: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    best_quartile: Mapped[str | None] = mapped_column(Text, nullable=True)
    h_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extras: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


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


# ── Limitations registry + manual overrides ────────────────────────────────


class UtWork(Base):
    """Canonical UT work harvested from Pure (ris.utwente.nl) via OAI-PMH."""

    __tablename__ = "ut_works"

    pure_uuid: Mapped[str] = mapped_column(Text, primary_key=True)
    doi_normalized: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    norm_title: Mapped[str] = mapped_column(Text, nullable=False)
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    work_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    publisher: Mapped[str | None] = mapped_column(Text, nullable=True)
    cerif_issn: Mapped[str | None] = mapped_column(Text, nullable=True)
    oa_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    journal_issn_l: Mapped[str | None] = mapped_column(
        ForeignKey("journals.issn_l"), nullable=True
    )
    first_seen_run: Mapped[int] = mapped_column(
        ForeignKey("harvest_runs.id"), nullable=False
    )
    last_seen_run: Mapped[int] = mapped_column(
        ForeignKey("harvest_runs.id"), nullable=False
    )
    retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = _tstamp()


class WorkIdentity(Base):
    """Cross-source identity link between an external record and a UT work.

    matched_by: 'doi' (auto-confirm), 'trgm:<threshold>[+v][+a]' (fuzzy,
    curation candidates), or 'verbatim' (shared source string).
    """

    __tablename__ = "work_identity"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_pk: Mapped[str] = mapped_column(Text, nullable=False)
    ut_work_id: Mapped[str] = mapped_column(
        ForeignKey("ut_works.pure_uuid", ondelete="CASCADE"), nullable=False
    )
    matched_by: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="candidate"
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _tstamp()
    updated_at: Mapped[datetime] = _tstamp()

    __table_args__ = (
        UniqueConstraint("source", "source_pk", name="uq_work_identity_source"),
    )


class Limitation(Base):
    """Registered caveat per data source/scope, surfaced in the UI."""

    __tablename__ = "limitations"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    hint: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False, server_default="info")
    url: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("severity IN ('info', 'warning')", name="ck_limitations_severity"),
    )


class ManualOverride(Base):
    """Curated value that re-ingestion must never overwrite."""

    __tablename__ = "manual_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    table_name: Mapped[str] = mapped_column(Text, nullable=False)
    row_key: Mapped[str] = mapped_column(Text, nullable=False)
    field: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    set_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    set_at: Mapped[datetime] = _tstamp()

    __table_args__ = (
        UniqueConstraint("table_name", "row_key", "field", name="uq_manual_overrides"),
    )
