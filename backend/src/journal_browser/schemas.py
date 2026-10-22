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
    in_quality_bar: bool = True
    deal_covered: bool = False
    twente_works: int = 0
    quartile: str | None = None
    twoyr_mean_citedness: float | None = None


class JournalSearchResponse(BaseModel):
    items: list[JournalListItem]
    total: int
    next_cursor: str | None = None
    facets: dict[str, dict[str, int]] = {}


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
    twente_relevant: bool = False
    journal_count: int = 0


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
    trend: list[StatsYear] = []
    scimagojr: list[ScimagojrOut] = []
    apc_aggregates: list[ApcAggregateOut] = []
    apc_evidence: list[ApcEvidenceOut] = []
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
