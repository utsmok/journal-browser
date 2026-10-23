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
    twente_works: int = 0
    quartile: str | None = None
    twoyr_mean_citedness: float | None = None
    oa_type: str = "subscription"
    # Most-recent OpenAPC evidence; None when the journal has no rows.
    apc_euro_mean: float | None = None
    apc_period: str | None = None


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
    twente_works: int
    shared_topics: int
    # Embedding-cosine similarity (0-1); null on the shared-topic fallback.
    similarity: float | None = None


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
    # Register links ([{url, text, category}]); None on rows not yet seeded.
    links: list[dict[str, Any]] | None = None
    journal_count: int = 0


class OpenalexInfo(BaseModel):
    """Venue-level OpenAlex source object (topics sorted count desc, nulls last)."""

    id: str | None = None
    url: str | None = None
    cited_by_count: int | None = None
    works_count: int | None = None
    host_organization_name: str | None = None
    first_publication_year: int | None = None
    last_publication_year: int | None = None
    topics: list[Any] = []


class OpenaireInfo(BaseModel):
    matched_works: int = 0


class UtOa(BaseModel):
    """ut-metadata oa_status distribution over a journal's UT works."""

    gold: int = 0
    hybrid: int = 0
    green: int = 0
    bronze: int = 0
    diamond: int = 0
    closed: int = 0
    unknown: int = 0


class TwenteMetrics(BaseModel):
    """OpenAlex view of Twente publications in this journal, plus
    ut-metadata-grounded totals when the canonical store is reachable
    (otherwise the ut_* keys are None)."""

    openalex_matched: int = 0
    fwci_avg: float | None = None
    fwci_n: int = 0
    retracted: int = 0
    cited_total: int = 0
    ut_total: int | None = None
    ut_retracted: int | None = None
    ut_oa: UtOa | None = None


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
    trend: list[StatsYear] = []
    scimagojr: list[ScimagojrOut] = []
    apc_aggregates: list[ApcAggregateOut] = []
    apc_evidence: list[ApcEvidenceOut] = []
    openalex: OpenalexInfo | None = None
    openaire: OpenaireInfo = OpenaireInfo()
    twente_metrics: TwenteMetrics = TwenteMetrics()
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
    institution: str
    ror: str
    harvests: list[FreshnessEntry]
    # max timestamps (or year/period maxima for yearly tables)
    tables: dict[str, Any] = {}
