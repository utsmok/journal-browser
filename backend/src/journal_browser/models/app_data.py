from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, TIMESTAMP
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

    __table_args__ = (UniqueConstraint("doc_slug", "block_key", name="uq_doc_edits_block"),)


class StatusChangeLog(Base):
    """Append-only audit of admin status flips across the review surfaces
    (author identities, work identities, feedback triage).

    One row per actual transition; no-op writes record nothing. `row_key`
    is the subject's primary key as a JSON object (compound keys) or
    scalar (single-column tables). `changed_by` stays null today — admin
    auth is one shared token — and is ready for named identities.
    """

    __tablename__ = "status_changes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    table_name: Mapped[str] = mapped_column(Text, nullable=False)
    row_key: Mapped[Any] = mapped_column(JSONB, nullable=False)
    field: Mapped[str] = mapped_column(Text, nullable=False, server_default="status")
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = _tstamp()

    __table_args__ = (Index("ix_status_changes_table_time", "table_name", "changed_at"),)


class UsageEvent(Base):
    """One anonymous client activity event (page view, search, or error).

    Written by POST /api/v1/usage/events from the frontend tracker; length
    caps live in the endpoint's pydantic models, not the columns. `ip` and
    `user_agent` are server-filled per batch; `country` is backfilled by
    jobs/enrich_usage_geo.py.
    """

    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    # page_view | search | error
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    # page_view dwell time
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    results_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # journals | funders | authors | publishers | orgunits
    search_scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    filters: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    ref_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    ref_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # js_error | unhandled_rejection | api_status
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    referrer: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    country: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    tz: Mapped[str | None] = mapped_column(Text, nullable=True)
    locale: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('page_view', 'search', 'error')", name="ck_usage_event_type"
        ),
        CheckConstraint(
            "search_scope IN ('journals', 'funders', 'authors', 'publishers', 'orgunits')",
            name="ck_usage_search_scope",
        ),
        CheckConstraint(
            "ref_type IN ('journal', 'funder', 'author', 'orgunit', 'publisher')",
            name="ck_usage_ref_type",
        ),
        CheckConstraint("(ref_type IS NULL) = (ref_id IS NULL)", name="ck_usage_ref_pair"),
        CheckConstraint(
            "source IN ('js_error', 'unhandled_rejection', 'api_status')", name="ck_usage_source"
        ),
        Index("ix_usage_events_ts", "ts"),
        Index("ix_usage_events_type_ts", "event_type", "ts"),
        Index("ix_usage_events_session", "session_id"),
    )
