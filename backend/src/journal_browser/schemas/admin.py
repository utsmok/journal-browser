"""Admin, ops, feedback, docs, and usage Pydantic schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..vocab import (
    DealJournalSource,
    DealStatus,
    FeedbackCategory,
    FeedbackPriority,
    FeedbackStatus,
    HarvestStatus,
    IdentityStatus,
    WorkIdentityStatus,
)
from .common import CapUsageEntry, SourceFreshness


class AdminRunOut(BaseModel):
    id: int
    source: str
    entity_type: str
    institution_id: int | None
    institution_code: str | None
    status: HarvestStatus
    started_at: datetime | None
    finished_at: datetime | None
    stats: dict[str, Any]


class AdminLastRunOut(BaseModel):
    id: int
    source: str
    entity_type: str
    institution_id: int | None
    institution_code: str | None
    status: HarvestStatus
    started_at: datetime | None
    finished_at: datetime | None


class AdminSummaryOut(BaseModel):
    """Dashboard counters for the admin overview (GET /admin/summary)."""

    failed_runs_24h: int
    running_runs: int
    flagged_deals: int
    open_feedback: int
    author_identity_candidates: int
    work_identity_candidates: int
    work_identity_missing: int
    last_run: AdminLastRunOut | None


class FlaggedDealOut(BaseModel):
    id: int
    publisher: str
    esac_id: str | None
    status: DealStatus
    duration: str | None
    journals: int
    reason: str | None


class AuthorIdentityAdminOut(BaseModel):
    """One identity-cascade row for the admin review list."""

    institution_id: int
    institution_code: str | None
    author_pure_uuid: str
    author_name: str | None
    source: str
    external_id: str
    status: IdentityStatus
    method: str | None
    confidence: float | None
    n_works: int
    orcid_corroborated: bool
    evidence: dict[str, Any]
    updated_at: datetime | None


class AdminExternalWorkOut(BaseModel):
    """One recent OpenAlex work of a candidate author, from the projection."""

    w_id: str
    title: str | None
    year: int | None
    doi: str | None
    venue: str | None


class AdminExternalAuthorOut(BaseModel):
    """Stored OpenAlex author profile (source_records) + recent works.

    Serves the identity review drawer from the harvest's stored payloads
    instead of the live API.
    """

    source_pk: str
    harvested_at: datetime | None
    author: dict[str, Any]
    works: list[AdminExternalWorkOut]


class WorkIdentityAdminOut(BaseModel):
    """One cross-source work-identity row for the admin review list.

    Flips are durable: every harvest write is on_conflict_do_nothing, so
    re-runs never overwrite an admin decision.
    """

    institution_id: int
    institution_code: str | None
    work_id: str
    work_title: str | None
    source: str
    source_pk: str
    matched_by: str
    confidence: float | None
    status: WorkIdentityStatus
    note: str | None
    updated_at: datetime | None


class AuthorIdentityPageOut(BaseModel):
    """Paged identity-cascade review queue (total is the unpaginated count)."""

    total: int
    offset: int = 0
    items: list[AuthorIdentityAdminOut]


class WorkIdentityPageOut(BaseModel):
    """Paged work-identity review queue (total is the unpaginated count)."""

    total: int
    offset: int = 0
    items: list[WorkIdentityAdminOut]


# --- Work identity bulk curation ---------------------------------------
# Admin bulk review of work_identity rows (POST /admin/work-identities/bulk
# and the jobs/bulk_work_identity.py deploy CLI). Kept as its own section;
# everything above serves the existing single-row surfaces.


class WorkIdentityBulkUpdate(BaseModel):
    """One row decision inside a bulk work-identity request."""

    source_pk: str
    status: WorkIdentityStatus
    note: str | None = Field(default=None, max_length=2000)


class WorkIdentityBulkIn(BaseModel):
    """POST /admin/work-identities/bulk: many rows, one reviewer, one source."""

    institution_id: int
    source: str
    reviewer: str = Field(max_length=200)
    updates: list[WorkIdentityBulkUpdate] = Field(max_length=5000)


class WorkIdentityBulkRowError(BaseModel):
    """One bulk row that could not be applied (e.g. unknown source_pk)."""

    source_pk: str
    error: str


class WorkIdentityBulkOut(BaseModel):
    """POST /admin/work-identities/bulk result: a tally plus per-row errors."""

    confirmed: int
    missing: int
    reopened: int
    unchanged: int
    errors: list[WorkIdentityBulkRowError] = []


class StatusChangeOut(BaseModel):
    """One audited admin status flip (status_changes rows)."""

    id: int
    table_name: str
    row_key: Any
    field: str
    old_value: str | None
    new_value: str
    note: str | None
    changed_by: str | None
    changed_at: datetime


class AdminInstitutionOut(BaseModel):
    code: str | None
    name: str
    short_name: str | None
    ror: str | None
    openalex_id: str | None
    pure_oai_base_url: str | None
    openaire_org_id: str | None
    data_window_start: int
    data_window_end: int | None
    library_url: str | None
    oa_guide_url: str | None
    support_email: str | None
    admin_contact: str | None
    research_portal_url: str | None
    active: bool
    require_confirmed_affiliation: bool
    # Set when this PUT rebuilt the institution's journal_flags rows
    # in-request (activation or a data-window change): the number of
    # materialized flags rows. None = no rebuild happened.
    rematerialized_journals: int | None = None


class OpsLastWaveStageOut(BaseModel):
    """One wave stage (a global harvest run) inside the latest wave cluster."""

    source: str
    entity_type: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None


class OpsLastWaveOut(BaseModel):
    """The most recent burst of global harvest runs (the nightly wave)."""

    window_start: datetime | None
    window_end: datetime | None
    stages: list[OpsLastWaveStageOut]
    failed: int
    running: int


class OpsScheduleOut(BaseModel):
    """A scheduled job's cron expression and its next fire time (UTC)."""

    name: str
    cron: str
    from_env: bool
    next_run_utc: datetime | None
    error: str | None = None


class OpsBackupOut(BaseModel):
    """The newest backup archive, or why none is visible to the backend."""

    available: bool
    detail: str | None = None
    file: str | None = None
    size_bytes: int | None = None
    modified_at: datetime | None = None


class AdminOpsStatusOut(BaseModel):
    """Ops dashboard payload (GET /admin/ops/status)."""

    generated_at: datetime
    last_wave: OpsLastWaveOut | None
    schedules: list[OpsScheduleOut]
    backup: OpsBackupOut
    sources: list[SourceFreshness]
    tables: dict[str, datetime | None]


class AdminDealJournal(BaseModel):
    issn: str
    issn_l: str | None
    journal_name: str | None
    source: DealJournalSource
    excluded: bool


class AdminDealOut(BaseModel):
    id: int
    publisher_id: int | None
    publisher: str | None
    esac_id: str | None
    status: DealStatus
    start_year: int | None
    end_year: int | None
    corresponding_authors_only: bool | None
    capped: bool
    cap_numbers: dict[str, Any] | None
    cap_text: str | None
    cap_usage: list[CapUsageEntry] | None = None
    summary: str | None
    journal_count: int
    participations: list[str]
    needs_curation: bool
    needs_curation_reason: str | None
    curation_resolved_reason: str | None


class AdminDealDetail(AdminDealOut):
    journals: list[AdminDealJournal]


class FeedbackAdminOut(BaseModel):
    id: int
    title: str
    description: str
    category: FeedbackCategory | None
    status: FeedbackStatus
    priority: FeedbackPriority
    page_url: str | None
    page_data: dict[str, Any]
    resolution_notes: str | None
    created_at: datetime
    updated_at: datetime


class FeedbackPatchOut(BaseModel):
    id: int
    status: FeedbackStatus
    priority: FeedbackPriority


class DocEditOut(BaseModel):
    slug: str
    block_key: str
    edited: bool


# ── Docs responses (dict payload shapes in routers/docs.py) ────────────────


class DocMetaOut(BaseModel):
    slug: str
    title: str
    summary: str
    group: str
    order: int
    edits: int


class DocBlock(BaseModel):
    key: str
    type: str
    text: str
    level: int | None = None
    lang: str | None = None
    edited: bool = False


class DocDetailOut(BaseModel):
    slug: str
    title: str
    group: str
    order: int
    blocks: list[DocBlock]


class UsageDayCount(BaseModel):
    """Per-day usage-event counts, one entry per calendar day."""

    date: str
    page_view: int
    search: int
    error: int


class UsageTopPath(BaseModel):
    path: str
    page_views: int
    avg_duration_ms: float | None


class UsageTopQuery(BaseModel):
    query: str
    count: int
    zero_share: float


class UsageTopRef(BaseModel):
    ref_type: str
    ref_id: str
    count: int


class UsageErrorGroup(BaseModel):
    source: str | None
    status: int | None
    message: str | None
    count: int
    last_ts: datetime


class UsageCountryCount(BaseModel):
    country: str
    count: int


class UsageSearchSplit(BaseModel):
    """Search events split into real queries vs default browse loads."""

    browse: int
    queries: int


class UsageEventOut(BaseModel):
    """One raw usage event as stored (admin event list)."""

    model_config = ConfigDict(from_attributes=True)

    # asyncpg hands the INET column back as IPv4Address/IPv6Address, not str.
    @field_validator("ip", mode="before")
    @classmethod
    def _ip_as_str(cls, v: object) -> str | None:
        return None if v is None else str(v)

    id: int
    ts: datetime
    event_type: str
    path: str
    duration_ms: int | None
    query: str | None
    is_browse: bool
    results_count: int | None
    search_scope: str | None
    filters: dict[str, Any] | None
    ref_type: str | None
    ref_id: str | None
    source: str | None
    message: str | None
    detail: str | None
    status: int | None
    referrer: str | None
    ip: str | None
    country: str | None
    user_agent: str | None
    tz: str | None
    locale: str | None
    session_id: str


class UsageEventsPageOut(BaseModel):
    """One offset page of the admin usage event list."""

    total: int
    items: list[UsageEventOut]


class UsageSummaryOut(BaseModel):
    """Admin usage snapshot over the trailing `days` window."""

    days: int
    totals: dict[str, int]
    searches: UsageSearchSplit
    daily: list[UsageDayCount]
    top_paths: list[UsageTopPath]
    top_queries: list[UsageTopQuery]
    top_refs: list[UsageTopRef]
    errors: list[UsageErrorGroup]
    countries: list[UsageCountryCount]
    sessions: int
