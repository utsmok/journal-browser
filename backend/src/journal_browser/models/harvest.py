from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _tstamp


class HarvestRun(Base):
    __tablename__ = "harvest_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    # NULL = global job (journals, deals, OpenAPC, ...); institution-scoped
    # jobs (pure, enrich, openaire, works stats) carry the institution id.
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), nullable=True)
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
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), nullable=True)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    last_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("harvest_runs.id"), nullable=True
    )
    updated_at: Mapped[datetime] = _tstamp()

    __table_args__ = (
        # Same vocabulary as ck_harvest_runs_status; NULL = never run.
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_harvest_state_status",
        ),
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
