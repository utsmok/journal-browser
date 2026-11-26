"""Shared Pydantic schemas reused across API domains."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..vocab import (
    DealStatus,
    FreshnessSchedule,
    FreshnessStatus,
    HarvestStatus,
    WorksSource,
)


class Attribution(BaseModel):
    source: str
    url: str | None = None
    caveat_codes: list[str] = []


class FunderFitOut(BaseModel):
    """How well one journal satisfies the selected funder's OA policy.

    status None = the funder's policy is text-only, no tier derivable."""

    status: Literal["compliant", "check", "no"] | None
    reasons: list[str] = []


class StatsYear(BaseModel):
    year: int
    works_count: int
    works_count_source: WorksSource = WorksSource.OPENALEX_INSTITUTION_FILTER
    oa_gold: int
    oa_hybrid: int
    oa_green: int
    oa_bronze: int
    oa_diamond: int
    oa_closed: int


class DealLinkOut(BaseModel):
    """Register link entry ([{url, text, category}], seeded by curation jobs)."""

    url: str | None = None
    text: str | None = None
    category: str | None = None


class CapUsageEntry(BaseModel):
    """One contract year's publisher-reported APC cap usage (admin-entered
    from library email updates; the harvest never rewrites it)."""

    year: int = Field(ge=1900, le=2100)
    pool: str | None = None
    total: int = Field(ge=0)
    used: int | None = Field(default=None, ge=0)
    as_of: str | None = None
    note: str | None = None


class DealOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    esac_id: str | None
    publisher_name: str | None
    # Group journals this deal covers (publisher detail only; None
    # elsewhere, where coverage is per journal).
    covers_in_group: int | None = None
    status: DealStatus
    start_year: int | None
    end_year: int | None
    duration_text: str | None
    corresponding_authors_only: bool | None
    summary: str | None
    conditions_text: str | None
    workflow_text: str | None
    article_types_text: str | None
    cap_text: str | None
    cap_numbers: dict[str, Any] | None
    contract_url: str | None
    openaccess_nl_url: str | None
    jct_data_url: str | None
    per_year_oa_counts: dict[str, Any] | None
    cap_usage: list[CapUsageEntry] | None = None
    needs_curation: bool
    needs_curation_reason: str | None
    # Register links; None on rows not yet seeded.
    links: list[DealLinkOut] | None = None
    # Covered journals for the institution. Only the deals list computes it;
    # deal cards embedded in a journal's detail carry None, never a false 0.
    journal_count: int | None = None
    # Observed APC spend for the institution's works in the deal's
    # effective journal list (latest-period evidence per DOI, mirror of
    # orgunit APC aggregation).
    apc_euro_total: float = 0.0
    apc_n: int = 0


class UTBucket(BaseModel):
    """Distinct works attributed to one faculty or research group."""

    name: str
    works: int


class UTAuthorRow(BaseModel):
    pure_uuid: str
    name: str
    faculty: str | None = None
    research_group: str | None = None
    works: int


class UTAuthorship(BaseModel):
    """Who at this institution authors the venue's canonical works:
    distinct works per faculty / research group and the top authors,
    over the same population the search card counts (so the numbers
    reconcile with journal_flags.works_count). n_ut_works counts rows
    with at least one UT author edge; venue totals can exceed it."""

    n_ut_works: int = 0
    faculties: list[UTBucket] = []
    research_groups: list[UTBucket] = []
    top_authors: list[UTAuthorRow] = []


class OpenalexOnlyAuthor(BaseModel):
    """One compact OpenAlex authorship of a gap work ({a, n, o})."""

    openalex_id: str
    name: str | None = None
    orcid: str | None = None


class UtAuthorAttribution(BaseModel):
    """Roster author matched on a gap work's OpenAlex authorships."""

    name: str
    orcid: str | None = None
    faculty: str | None = None
    research_group: str | None = None
    institute: str | None = None


class WorkParent(BaseModel):
    """One parent work of a store row (compact {id, name, rel}): id is
    the bare OpenAlex W-id, rel one of volume/component/data-series/part
    (chapter of a book, figure of a paper, ...)."""

    id: str | None = None
    name: str | None = None
    rel: str | None = None


class GapGroupParent(BaseModel):
    """The main work a group entry's missing parts belong to: the parts'
    primary parent (the first rel=volume parent among a part's
    parent_works, else the first listed parent). name comes from the
    parts' parent_works (registry title when the registry row has one);
    work_type/doi/pure_registered are null without an openalex_work_parents
    row (parts backfill pending). pure_registered is derived live from the
    works table and false includes no-DOI parents."""

    w_id: str | None = None
    name: str | None = None
    work_type: str | None = None
    doi: str | None = None
    pure_registered: bool | None = None


class OpenalexOnlyWork(BaseModel):
    title: str | None = None
    year: int | None = None
    doi: str | None = None
    oa_status: str | None = None
    work_type: str | None = None
    venue: str | None = None
    openalex_id: str | None = None
    openalex_url: str | None = None
    authors: list[OpenalexOnlyAuthor] = []
    ut_authors: list[UtAuthorAttribution] = []
    journal_issn_l: str | None = None
    journal_title: str | None = None
    publisher_name: str | None = None
    # Work parts (OpenAlex, Nov 2026): compact parent works and the
    # is_part flag — chapter of a book when a parent has rel=volume.
    parent_works: list[WorkParent] = []
    is_part: bool = False
    # Why the row is not truly missing from Pure, when a record was
    # identified; None = likely missing. pure_match_url is that record's
    # public page (None without a portal URL).
    pure_match: Literal["doi_in_pure", "parent_book_in_pure", "same_title_in_pure"] | None = None
    pure_match_url: str | None = None


class OpenalexOnlySingle(OpenalexOnlyWork):
    """One standalone gap work (no parent works): all work-row fields at
    the top level."""

    kind: Literal["single"] = "single"


class OpenalexOnlyGroup(BaseModel):
    """One main work with its missing parts. A group exists when any part
    of the work is missing from Pure; parts hold only those missing works
    (registered parts never enter the gap set) and the parent itself may
    well be registered (pure_registered true)."""

    kind: Literal["group"] = "group"
    parent: GapGroupParent
    parts: list[OpenalexOnlyWork] = []
    parts_total: int = 0


OpenalexOnlyEntry = Annotated[OpenalexOnlySingle | OpenalexOnlyGroup, Field(discriminator="kind")]


class OpenalexOnly(BaseModel):
    """OpenAlex store works attributed to the venue or to the unit's
    member authors whose DOI matches no Pure work — candidates missing
    from the CRIS. items holds the grouped entries (missing parts
    collected under their main work), capped; total counts works and
    entries_total counts entries (before the cap), both exact.
    available=False when the openalex_works projection never ran
    (frontend hides the card). parts_counts carries unfiltered totals per
    part kind (all/chapter/part/standalone)."""

    total: int = 0
    entries_total: int = 0
    items: list[OpenalexOnlyEntry] = []
    available: bool = True
    parts_counts: dict[str, int] = {}


class ChapterBook(BaseModel):
    """One parent book of the parts rollup: a distinct volume parent of
    the page's chapter-kind gap works, with its chapter count and up to
    3 sample chapter titles."""

    parent_id: str | None = None
    name: str
    chapters: int
    sample: list[str] = []


class PartsRollup(BaseModel):
    """Chapter/book rollup over the page's full openalex-only population
    (before the gap card's item cap): chapters_total counts chapter-kind
    works (is_part with a rel=volume parent), books_total the distinct
    parents. books is the top 10 by chapter count."""

    chapters_total: int = 0
    books_total: int = 0
    books: list[ChapterBook] = []


class CrisGapsResponse(BaseModel):
    """Lazy-loaded CRIS gaps + book-chapter rollup for detail pages."""

    openalex_only: OpenalexOnly
    chapter_rollup: PartsRollup = PartsRollup()


class LimitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    source: str
    scope: str
    hint: str
    severity: str
    url: str | None


class FreshnessEntry(BaseModel):
    source: str
    entity_type: str
    filter_set: str
    status: str | None
    finished_at: datetime | None
    stats: dict[str, Any] | None


class DegradedSource(BaseModel):
    """A serving-time source currently answering in degraded mode."""

    source: str
    detail: str
    since: datetime


class SourceFreshness(BaseModel):
    """How fresh one data source is, for one institution or for all of them.
    services/freshness.py defines the sources, their schedules and the
    statuses."""

    source: str
    # The institution whose own harvest this row describes; None for a
    # source shared by all institutions.
    institution_code: str | None = None
    schedule: FreshnessSchedule
    # Hours between the successful runs the schedule promises; None for a
    # job that runs by hand.
    expected_interval_hours: int | None = None
    status: FreshnessStatus
    last_success_at: datetime | None = None
    # The newest run, so that a failure can be told from a missing refresh.
    last_run_at: datetime | None = None
    last_run_status: HarvestStatus | None = None
    # Entity types whose newest run failed.
    failed_parts: list[str] = []


class FreshnessResponse(BaseModel):
    """Config comes from the institution row; unset optional fields are
    None rather than global defaults."""

    institution: str
    institution_short: str | None = None
    ror: str | None = None
    library_url: str | None = None
    oa_guide_url: str | None = None
    support_email: str | None = None
    admin_contact: str | None = None
    research_portal_url: str | None = None
    data_window_start: int = 2020
    data_window_end: int | None = None
    harvests: list[FreshnessEntry]
    # This institution's own sources, then those shared by all institutions.
    sources: list[SourceFreshness]
    # The oldest last success among the core sources; the footer's date.
    data_updated_at: datetime | None = None
    degraded: list[DegradedSource] = []


class PartnerSummary(BaseModel):
    """Compact partner rollup shown on org-unit and author detail pages."""

    ror: str
    name: str
    org_type: str | None = None
    country_code: str | None = None
    city: str | None = None
    works: int
    oa_share: float | None = None


class TopicMassRow(BaseModel):
    name: str
    n: float


class FacetCount(BaseModel):
    """One facet value and the number of works in the result set that
    match it."""

    value: str
    label: str | None = None
    count: int
