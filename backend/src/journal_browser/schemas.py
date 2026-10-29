"""Pydantic response schemas for the API (openapi-typescript feeds on these)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .vocab import (
    DealJournalSource,
    DealStatus,
    FeedbackCategory,
    FeedbackPriority,
    FeedbackStatus,
    HarvestStatus,
    OaType,
    WorksSource,
)


class Attribution(BaseModel):
    source: str
    url: str | None = None
    caveat_codes: list[str] = []


class JournalListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    issn_l: str
    title: str | None
    publisher_name: str | None
    # Top-level parent publisher (OpenAlex lineage root, e.g. Wolters
    # Kluwer above the LWW imprint); the canonical browse/join key.
    publisher_canonical: str | None = None
    is_oa: bool | None
    is_in_doaj: bool | None
    in_scimago: bool = False
    last_active_year: int | None = None
    deal_covered: bool = False
    works: int = 0
    quartile: str | None = None
    twoyr_mean_citedness: float | None = None
    oa_type: OaType = OaType.SUBSCRIPTION
    # OpenAlex primary topic (first entry of the topics list); None when the
    # journal has no topics.
    primary_topic: str | None = None
    # Display APC for results rows: OpenAlex list price when known
    # (apc_price + apc_currency, EUR preferred), else the OpenAPC observed
    # range over the journal's newest two evidence periods (apc_low/high)
    # with per-period stats for the tooltip. All None without either source.
    apc_source: str | None = None
    apc_currency: str | None = None
    apc_price: float | None = None
    apc_low: float | None = None
    apc_high: float | None = None
    apc_stats: list["ApcAggregateOut"] = []


class JournalSearchResponse(BaseModel):
    items: list[JournalListItem]
    total: int
    next_cursor: str | None = None
    fuzzy: bool = False
    facets: dict[str, dict[str, int]] = {}


class SimilarJournalItem(BaseModel):
    issn_l: str
    title: str | None
    publisher_name: str | None
    publisher_canonical: str | None = None
    quartile: str | None
    is_oa: bool | None
    deal_covered: bool
    works: int
    shared_topics: int
    # Embedding-cosine similarity (0-1); null on the shared-topic fallback.
    similarity: float | None = None


class SimilarJournalsBundle(BaseModel):
    """Similar-journal lists: UT-publishing venues and deal-covered venues as
    teaser cuts, plus the general list."""

    institution: list[SimilarJournalItem]
    deals: list[SimilarJournalItem]
    all: list[SimilarJournalItem]


class ApcAggregateOut(BaseModel):
    period: int
    article_count: int
    euro_min: float | None
    euro_max: float | None
    euro_mean: float | None


class ApcEvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    doi: str | None
    period: int | None
    euro: float | None
    is_hybrid: bool | None
    agreement: str | None
    issn_l: str | None


class ScimagojrOut(BaseModel):
    year: int
    sjr: float | None
    best_quartile: str | None
    h_index: int | None


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
    needs_curation: bool
    needs_curation_reason: str | None
    # Register links; None on rows not yet seeded.
    links: list[DealLinkOut] | None = None
    journal_count: int = 0


class OpenalexTopicOut(BaseModel):
    """Topic entry of an OpenAlex source object (sorted count desc)."""

    id: str | None = None
    display_name: str | None = None
    count: int | None = None
    score: float | None = None
    subfield: dict[str, Any] | None = None
    field: dict[str, Any] | None = None
    domain: dict[str, Any] | None = None


class OpenalexInfo(BaseModel):
    """Venue-level OpenAlex source object (topics sorted count desc, nulls last)."""

    id: str | None = None
    url: str | None = None
    cited_by_count: int | None = None
    works_count: int | None = None
    host_organization_name: str | None = None
    first_publication_year: int | None = None
    last_publication_year: int | None = None
    topics: list[OpenalexTopicOut] = []


class OpenaireInfo(BaseModel):
    matched_works: int = 0


class CanonicalOa(BaseModel):
    """ut-metadata oa_status distribution over a journal's works."""

    gold: int = 0
    hybrid: int = 0
    green: int = 0
    bronze: int = 0
    diamond: int = 0
    closed: int = 0
    unknown: int = 0


class InstitutionMetrics(BaseModel):
    """OpenAlex view of this institution's publications in this journal,
    plus canonical-store totals when the external works store is reachable
    (otherwise the canonical_* keys are None)."""

    openalex_matched: int = 0
    fwci_avg: float | None = None
    fwci_n: int = 0
    retracted: int = 0
    cited_total: int = 0
    canonical_total: int | None = None
    canonical_retracted: int | None = None
    canonical_oa: CanonicalOa | None = None


class WorkItem(BaseModel):
    id: str | None = None
    url: str | None = None
    doi: str | None = None
    title: str | None = None
    year: int | None = None
    oa_status: str | None = None
    fwci: float | None = None
    cited_by_count: int = 0
    is_retracted: bool | None = None
    type: str | None = None
    # ut-metadata provenance: canonical work type, and whether the item is
    # backed by an OpenAlex works_stats row.
    work_type: str | None = None
    in_openalex: bool | None = None


class WorksPage(BaseModel):
    items: list[WorkItem]
    total: int
    page: int
    page_size: int


class JournalDetailResponse(BaseModel):
    journal: JournalListItem
    issns: list[str] = []
    alternate_titles: list[str] = []
    topics: list[Any] = []
    apc_prices: list[Any] = []
    summary_stats: dict[str, Any] | None = None
    counts_by_year: list[Any] = []
    homepage_url: str | None = None
    doaj_homepage_url: str | None = None
    type: str | None = None
    harvested_at: datetime | None = None
    deals: list[DealOut] = []
    stats: list[StatsYear] = []
    stats_totals: dict[str, int] = {}
    scimagojr: list[ScimagojrOut] = []
    apc_aggregates: list[ApcAggregateOut] = []
    apc_evidence: list[ApcEvidenceOut] = []
    openalex: OpenalexInfo | None = None
    openaire: OpenaireInfo = OpenaireInfo()
    institution_metrics: InstitutionMetrics = InstitutionMetrics()
    attribution: dict[str, Attribution] = {}


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
    data_window_end: int = 0  # 0 = open
    harvests: list[FreshnessEntry]
    # max timestamps (or year/period maxima for yearly tables)
    tables: dict[str, Any] = {}


# ── Author browsing (ut-metadata ingest) ───────────────────────────────────


class AuthorFacet(BaseModel):
    value: str
    count: int


class AuthorItem(BaseModel):
    pure_uuid: str
    name: str
    faculty: str | None
    research_group: str | None
    n_works: int
    orcid: str | None
    confirmed: bool
    last_pub_year: int | None = None
    primary_topic: str | None = None


class AuthorSearchResponse(BaseModel):
    enabled: bool
    total: int
    offset: int = 0
    sort: str = "works_desc"
    items: list[AuthorItem]
    # faculty/org/works/last_pub/topic buckets under all filters except the
    # facet's own dimension; has_orcid is boolean and has no facet list.
    facets: dict[str, list[AuthorFacet]] = {}


class AuthorOut(BaseModel):
    pure_uuid: str
    name: str
    orcid: str | None
    openalex_author_id: str | None
    openaire_person_id: str | None
    crossref_orcid: str | None
    faculty: str | None
    research_group: str | None
    orgs: list[str]
    n_works: int


class AuthorYearRow(BaseModel):
    year: int
    total: int
    gold: int
    green: int
    hybrid: int
    bronze: int
    closed: int


class AuthorJournalRow(BaseModel):
    issn_l: str
    title: str | None
    n_works: int
    oa_type: str


class AuthorTopicRow(BaseModel):
    name: str
    n: int


class AuthorSimilarJournal(BaseModel):
    issn_l: str
    title: str | None
    score: float
    oa_type: str
    deal_covered: bool


class AuthorSimilarBundle(BaseModel):
    all: list[AuthorSimilarJournal]
    deals: list[AuthorSimilarJournal]
    diamond: list[AuthorSimilarJournal]


class AuthorAlternative(BaseModel):
    issn_l: str
    title: str | None
    n_works: int
    options: list[AuthorSimilarJournal]


class AuthorWorkItem(BaseModel):
    pure_uuid: str
    title: str
    year: int
    doi: str | None
    oa_status: str | None
    journal_issn_l: str | None
    journal_title: str | None


class AuthorProfileResponse(BaseModel):
    author: AuthorOut
    oa_by_year: list[AuthorYearRow]
    journals: list[AuthorJournalRow]
    topics: list[AuthorTopicRow]
    similar: AuthorSimilarBundle
    alternatives: list[AuthorAlternative]
    works: list[AuthorWorkItem]


# ── Publisher browsing (journals grouped per publisher_name) ───────────────


class TopicMassRow(BaseModel):
    name: str
    n: float


class PublisherApcSummary(BaseModel):
    n_journals: int
    eur_min: float | None = None
    eur_max: float | None = None


class PublisherListItem(BaseModel):
    name: str
    n_journals: int
    n_works: int
    deal_journals: int
    # Journal counts per OA type (gold/diamond/hybrid/subscription).
    oa_types: dict[str, int]
    quartiles: dict[str, int]
    apc: PublisherApcSummary
    topics: list[TopicMassRow] = []


class PublisherSearchResponse(BaseModel):
    items: list[PublisherListItem]
    total: int
    facets: dict[str, dict[str, int]] = {}


class DealDiscrepancyRow(BaseModel):
    """A group journal covered by another publisher's deal: a publisher
    flip or stale ESAC entry, flagged for follow-up rather than shown as
    this publisher's agreement."""

    title: str | None
    publisher_name: str | None
    deal_publisher: str | None


class PublisherDetailResponse(BaseModel):
    publisher: PublisherListItem
    journals: list[JournalListItem]
    deals: list[DealOut] = []
    deal_discrepancies: list[DealDiscrepancyRow] = []
    n_discrepancies: int = 0
    works_by_year: list[StatsYear] = []


# ── Org-unit browsing (faculties + research groups) ────────────────────────


class OrgUnitItem(BaseModel):
    level: Literal["faculty", "group"]
    name: str
    faculty: str | None = None
    n_authors: int
    n_works: int
    # Faculty level only: distinct child research groups.
    n_groups: int | None = None
    deal_works: int
    apc_euro_total: float
    apc_n: int
    topics: list[TopicMassRow] = []


class OrgUnitSearchResponse(BaseModel):
    level: str
    items: list[OrgUnitItem]
    total: int
    facets: dict[str, dict[str, int]] = {}


class OrgUnitJournalRow(BaseModel):
    issn_l: str
    title: str | None
    n_works: int
    deal_covered: bool
    oa_type: str
    quartile: str | None


class OrgUnitAuthorRow(BaseModel):
    pure_uuid: str
    name: str
    n_works: int
    orcid: str | None
    primary_topic: str | None


class DealUsageRow(BaseModel):
    label: str
    n_works: int
    euro: float


class OrgUnitDetailResponse(BaseModel):
    unit: OrgUnitItem
    # Faculty level only: child groups, works desc.
    groups: list[OrgUnitItem] | None = None
    journals: list[OrgUnitJournalRow] = []
    authors: list[OrgUnitAuthorRow] = []
    works_by_year: list[StatsYear] = []
    deal_usage: list[DealUsageRow] = []


# ── Admin responses (dict payload shapes in routers/admin.py) ──────────────


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


class FlaggedDealOut(BaseModel):
    id: int
    publisher: str
    esac_id: str | None
    status: DealStatus
    duration: str | None
    journals: int
    reason: str | None


class AdminInstitutionOut(BaseModel):
    code: str | None
    name: str
    short_name: str | None
    ror: str | None
    openalex_id: str | None
    pure_oai_base_url: str | None
    openaire_org_id: str | None
    data_window_start: int
    data_window_end: int
    library_url: str | None
    oa_guide_url: str | None
    support_email: str | None
    admin_contact: str | None
    research_portal_url: str | None
    active: bool
    require_confirmed_affiliation: bool


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
    summary: str | None
    journal_count: int
    participations: list[str]
    needs_curation: bool
    needs_curation_reason: str | None


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
