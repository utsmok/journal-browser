"""Pydantic response schemas for the API (openapi-typescript feeds on these)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class Attribution(BaseModel):
    source: str
    url: str | None = None
    caveat_codes: list[str] = []


class JournalListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    issn_l: str
    title: str | None
    publisher_name: str | None
    is_oa: bool | None
    is_in_doaj: bool | None
    in_scimago: bool = False
    last_active_year: int | None = None
    deal_covered: bool = False
    works: int = 0
    quartile: str | None = None
    twoyr_mean_citedness: float | None = None
    oa_type: str = "subscription"
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
    works_count_source: str = "openalex_institution_filter"
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
    status: str
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


class AuthorItem(BaseModel):
    pure_uuid: str
    name: str
    faculty: str | None
    research_group: str | None
    n_works: int
    orcid: str | None


class AuthorSearchResponse(BaseModel):
    enabled: bool
    total: int
    items: list[AuthorItem]


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
