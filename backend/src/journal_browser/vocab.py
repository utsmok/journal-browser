"""Single home for every API vocabulary; DB CHECK constraints, pydantic
models, and the generated TypeScript unions all derive from these enums
(via FastAPI response models + openapi-typescript). A new value lands here
first, then in the owning CHECK constraint."""

from enum import StrEnum


class OaType(StrEnum):
    """Journal-level OA classification (journals.oa_type; services/search.py
    SQL case + Python mirror, search filter vocabulary).

    Member order is the facet display order (most open first); every
    oa_type facet/composition dict iterates OA_TYPES, so do not reorder
    alphabetically."""

    DIAMOND = "diamond"
    GOLD = "gold"
    HYBRID = "hybrid"
    GENERIC = "generic"
    SUBSCRIPTION = "subscription"


class GreenOa(StrEnum):
    """Best green (self-archiving) route per Jisc Open Policy Finder
    (journals.jisc_allows_sa_* / jisc_in_opf; search filter + facet
    vocabulary). "none" = swept but no route permitted (or OA prohibited
    outright); never-swept journals land in no bucket."""

    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    PUBLISHED = "published"
    NONE = "none"


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
    """feedback_items.category (ck_feedback_items_category)."""

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
    """works.oa_status and openalex_works.oa_status
    (ck_works_oa_status / ck_openalex_works_oa_status)."""

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


class IdentityStatus(StrEnum):
    """author_identities.status (ck_author_identities_status)."""

    CONFIRMED = "confirmed"
    CANDIDATE = "candidate"
    REJECTED = "rejected"


class WorkIdentityStatus(StrEnum):
    """work_identity.status (ck_work_identity_status).

    'confirmed' = DOI-verified link (auto, admin-reaffirmed); 'missing' =
    recorded lookup miss (no evidence, not low confidence); 'candidate' =
    fuzzy match awaiting review.
    """

    CONFIRMED = "confirmed"
    MISSING = "missing"
    CANDIDATE = "candidate"
