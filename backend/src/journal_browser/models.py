"""Database schema: harvest bookkeeping, landing store, and domain tables.

Landing store (ut-metadata pattern): verbatim payloads in `source_records`
(content-hash versioned, append-only) plus file-level raw copies in
`raw_files`. Normalized domain tables are rebuildable from the landing
store; `manual_overrides` survives every re-ingestion.
"""

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
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
    # NULL = global job (journals, deals, OpenAPC, ...); institution-scoped
    # jobs (pure, enrich, openaire, works stats) carry the institution id.
    institution_id: Mapped[int | None] = mapped_column(
        ForeignKey("institutions.id"), nullable=True
    )
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
        Index("ix_harvest_runs_institution", "institution_id", "id"),
    )


class HarvestState(Base):
    __tablename__ = "harvest_state"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    filter_set: Mapped[str] = mapped_column(Text, nullable=False)
    institution_id: Mapped[int | None] = mapped_column(
        ForeignKey("institutions.id"), nullable=True
    )
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    last_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("harvest_runs.id"), nullable=True
    )
    updated_at: Mapped[datetime] = _tstamp()

    __table_args__ = (
        # Partial uniques keep one state row per key for global (NULL) and
        # institution-scoped rows separately; same pattern as deal_journals.
        Index(
            "uq_harvest_state_global",
            "source",
            "entity_type",
            "filter_set",
            unique=True,
            postgresql_where=text("institution_id IS NULL"),
        ),
        Index(
            "uq_harvest_state_scoped",
            "source",
            "entity_type",
            "filter_set",
            "institution_id",
            unique=True,
            postgresql_where=text("institution_id IS NOT NULL"),
        ),
    )


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


class OpenalexPublisher(Base):
    """OpenAlex publisher lineage cache (jobs/harvest_publishers.py).

    One row per publisher entity attempted; lineage is [self, ..., root]
    and canonical is the root (last element). A NULL lineage marks a fetch
    that failed (404 etc.), so re-runs skip it instead of retrying.
    """

    __tablename__ = "openalex_publishers"

    openalex_id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    lineage: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    canonical_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = _tstamp()


class Institution(Base):
    """Institution configuration carrier.

    Every row is a real-world institution (JCT sheets populate participation
    rows without a code); only hosted institutions carry `code` + `active`.
    Env vars seed the default row once; afterwards the table is
    authoritative.
    """

    __tablename__ = "institutions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    short_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    ror: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    openalex_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Per-institution harvest sources.
    pure_oai_base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    openaire_org_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optional external canonical-works Postgres (ut-metadata style),
    # read-only. Empty = the enrichment degrades to works_stats-only.
    external_works_dsn: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Publication-year data window (inclusive); end 0 = open (to now).
    data_window_start: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("2020")
    )
    data_window_end: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    # Display fields served to the frontend via /meta/freshness.
    library_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    oa_guide_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    support_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_contact: Mapped[str | None] = mapped_column(Text, nullable=True)
    research_portal_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Hosted + served at /{code}/...; the env-seeded home institution resolves
    # by ROR, not by a flag.
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Author search lists only authors whose Pure affiliation resolves to
    # this institution's ROR (authors.confirmed); profiles stay accessible.
    require_confirmed_affiliation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    @property
    def window_years(self) -> list[int]:
        """Inclusive publication-year window, capped at the current year."""
        import datetime as dt

        last = self.data_window_end or dt.date.today().year
        return list(range(self.data_window_start, min(last, dt.date.today().year) + 1))


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
    # Admin-removed from the deal (PUT /admin/deals/{id}/journals). The row
    # is kept so the JCT upsert cannot resurrect it; hidden from coverage.
    excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    __table_args__ = (
        CheckConstraint(
            "source IN ('jct', 'manual', 'publisher-pattern')",
            name="ck_deal_journals_source",
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


# ── Journals ────────────────────────────────────────────────────────────────


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


# ── Per-institution journal state + works corpus ────────────────────────────


class CacheEpoch(Base):
    """One-row harvest counter; in-process caches key on bumped_at so any
    harvest step invalidates them across processes (services/search.py,
    services/publishers.py). Bumped by run_harvest and the denorm
    refreshes."""

    __tablename__ = "cache_epoch"

    id: Mapped[int] = mapped_column(primary_key=True)
    bumped_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )


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


class Author(Base):
    """Per-institution researcher, ingested from an external
    canonical-publications database (ut-metadata core_author_link).

    Faculty / research_group / orgs are derived at ingest time (pure person
    CERIF affiliations, canonical-person augmentation as fallback); n_works
    counts stored edges to the institution's non-retired works. confirmed
    marks a CERIF affiliation resolving to the institution's ROR;
    last_pub_year and primary_topic derive from the stored work edges."""

    __tablename__ = "authors"

    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), primary_key=True
    )
    pure_uuid: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    orcid: Mapped[str | None] = mapped_column(Text, nullable=True)
    openalex_author_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    openaire_person_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    crossref_orcid: Mapped[str | None] = mapped_column(Text, nullable=True)
    faculty: Mapped[str | None] = mapped_column(Text, nullable=True)
    research_group: Mapped[str | None] = mapped_column(Text, nullable=True)
    orgs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'"))
    n_works: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    last_pub_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    primary_topic: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = _tstamp()


class AuthorWork(Base):
    """Author ↔ work membership, resolved via the external canonical work
    ids (work_authors) onto local works.pure_uuid. Full-replace per
    institution at ingest; retired works drop out on the next run."""

    __tablename__ = "author_works"

    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), primary_key=True
    )
    author_pure_uuid: Mapped[str] = mapped_column(Text, primary_key=True)
    work_pure_uuid: Mapped[str] = mapped_column(Text, primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["institution_id", "author_pure_uuid"],
            ["authors.institution_id", "authors.pure_uuid"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["institution_id", "work_pure_uuid"],
            ["works.institution_id", "works.pure_uuid"],
            ondelete="CASCADE",
        ),
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
