from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, _tstamp


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


class Feedback(Base):
    """User-reported issue from the in-app feedback widget.

    `page_data` carries the frontend dump of every TanStack Query cache
    entry live on the page at submit time, so most reports (data issues)
    arrive with the exact API responses the reporter saw.
    """

    __tablename__ = "feedback_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # bug | data | feature | improvement | other (ck_feedback_items_category)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    # todo | in_progress | done | wontfix
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="todo")
    # low | normal | high | critical
    priority: Mapped[str] = mapped_column(Text, nullable=False, server_default="normal")
    page_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _tstamp()
    updated_at: Mapped[datetime] = _tstamp()

    __table_args__ = (
        CheckConstraint(
            "status IN ('todo', 'in_progress', 'done', 'wontfix')",
            name="ck_feedback_status",
        ),
        CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'critical')",
            name="ck_feedback_priority",
        ),
        CheckConstraint(
            "category IN ('bug', 'data', 'feature', 'improvement', 'other')",
            name="ck_feedback_items_category",
        ),
    )


class DocEdit(Base):
    """Admin replacement for one markdown block of a served doc (docs/).

    Applied at read time by the /docs endpoints, so edits survive without
    touching the source files (which stay host-owned). `original_hash` is
    the sha256 of the block text the editor saw — provenance only, never
    verified on write.
    """

    __tablename__ = "doc_edits"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    doc_slug: Mapped[str] = mapped_column(Text, nullable=False)
    block_key: Mapped[str] = mapped_column(Text, nullable=False)
    original_hash: Mapped[str] = mapped_column(Text, nullable=False)
    replacement: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = _tstamp()

    __table_args__ = (
        UniqueConstraint("doc_slug", "block_key", name="uq_doc_edits_block"),
    )
