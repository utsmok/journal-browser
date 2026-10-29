"""Single home for every API vocabulary; DB CHECK constraints, pydantic
models, and the generated TypeScript unions all derive from these enums
(via FastAPI response models + openapi-typescript). A new value lands here
first, then in the owning CHECK constraint."""

from enum import StrEnum


class OaType(StrEnum):
    """Journal-level OA classification (journals.oa_type; services/search.py
    SQL case + Python mirror, search filter vocabulary)."""

    GOLD = "gold"
    DIAMOND = "diamond"
    GENERIC = "generic"
    HYBRID = "hybrid"
    SUBSCRIPTION = "subscription"


class DealStatus(StrEnum):
    """deals.status (ck_deals_status)."""

    CURRENT = "current"
    ARCHIVE = "archive"


class DealJournalSource(StrEnum):
    """deal_journals.source (provenance of the membership row)."""

    JCT = "jct"
    MANUAL = "manual"
    PUBLISHER_PATTERN = "publisher-pattern"


class FeedbackCategory(StrEnum):
    """feedback_items.category (the /feedback intake surface; the DB has no
    CHECK yet — the API set is authoritative)."""

    BUG = "bug"
    DATA = "data"
    FEATURE = "feature"
    IMPROVEMENT = "improvement"
    OTHER = "other"


class FeedbackStatus(StrEnum):
    """feedback_items.status (ck_feedback_status)."""

    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    WONTFIX = "wontfix"


class FeedbackPriority(StrEnum):
    """feedback_items.priority (ck_feedback_priority)."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class WorkOaStatus(StrEnum):
    """works.oa_status (per-work OA color; no DB constraint yet)."""

    GOLD = "gold"
    HYBRID = "hybrid"
    GREEN = "green"
    BRONZE = "bronze"
    DIAMOND = "diamond"
    CLOSED = "closed"


class WorksSource(StrEnum):
    """institution_works_stats.works_count_source (which pipeline filled the
    yearly counts)."""

    PURE_CANON = "pure_canon"
    OPENALEX_INSTITUTION_FILTER = "openalex_institution_filter"


class HarvestStatus(StrEnum):
    """harvest_runs.status (ck_harvest_runs_status)."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
