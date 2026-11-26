"""Journal, search, recommendation, and detail Pydantic schemas."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..vocab import (
    ApcSource,
    GreenOa,
    OaType,
)
from .common import Attribution, DealOut, FunderFitOut, OpenalexOnly, StatsYear, UTAuthorship


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
    # True when every effective covering deal's latest cap_usage entry has
    # used >= total; free OA publishing no longer guaranteed (harvest.denorm).
    deal_cap_reached: bool = False
    works: int = 0
    quartile: str | None = None
    twoyr_mean_citedness: float | None = None
    oa_type: OaType = OaType.SUBSCRIPTION
    # OpenAlex venue type (journal, book series, conference, ...); NULL for
    # untyped sources.
    pub_type: str | None = None
    # Modal work language (ISO 639-1, e.g. "en"); NULL = never observed.
    language: str | None = None
    # OpenAlex primary topic (first entry of the topics list); None when the
    # journal has no topics.
    primary_topic: str | None = None
    # The journal's APC as two concepts. The shown price is the publisher's
    # list price when one is known: apc_source says openalex or doaj,
    # apc_price is in apc_currency (EUR when an exchange rate exists, else
    # the original currency), apc_original_* keep the source amount, and
    # apc_year is the year that source was last harvested. Without a list
    # price the shown price is the mean amount paid: apc_source openapc,
    # apc_price in EUR over apc_year, the newest OpenAPC period with a
    # paid article. Sorting, the APC filter and the finder budget use the
    # shown price. The paid block (apc_low/apc_high over the newest two
    # paid periods, apc_stats per period) is filled whenever the journal
    # has paid articles. All None without any price.
    apc_source: ApcSource | None = None
    apc_currency: str | None = None
    apc_price: float | None = None
    apc_year: int | None = None
    apc_original_currency: str | None = None
    apc_original_price: float | None = None
    apc_low: float | None = None
    apc_high: float | None = None
    apc_stats: list["ApcAggregateOut"] = []
    # Present only when the list query selects a funder.
    funder_fit: FunderFitOut | None = None


class JournalSearchResponse(BaseModel):
    items: list[JournalListItem]
    total: int
    next_cursor: str | None = None
    fuzzy: bool = False
    facets: dict[str, dict[str, int]] = {}


class JournalBatchDeal(BaseModel):
    """A current deal that covers the journal for the requesting institution."""

    id: int
    publisher_name: str | None = None
    duration_text: str | None = None


class JournalBatchItem(JournalListItem):
    """List row plus what a saved-journal table needs: the names of the
    covering deals and the best green OA route."""

    deals: list[JournalBatchDeal] = []
    green_oa: GreenOa | None = None


class JournalBatchResponse(BaseModel):
    items: list[JournalBatchItem]
    #: Requested ISSN-Ls with no row in this institution's browsable corpus.
    missing: list[str]


# ── Guided Journal Finder recommendations ──────────────────────────────────


BudgetMode = Literal["none", "capped", "funder_pays", "any"]


class RecommendRequest(BaseModel):
    """Guided Journal Finder request; manuscript text is embedded locally
    and never logged or persisted."""

    title: str = Field(default="", max_length=400)
    abstract: str = Field(default="", max_length=6000)
    funder_id: int | None = None
    budget_mode: BudgetMode = "none"
    max_apc_eur: int | None = Field(default=None, ge=0, le=50000)
    prefer_institution_history: bool = True
    prefer_established: bool = False
    include_non_journals: bool = False
    limit: int = Field(default=8, ge=1, le=20)

    @model_validator(mode="after")
    def _validate_manuscript_text(self) -> "RecommendRequest":
        combined = f"{self.title.strip()} {self.abstract.strip()}".strip()
        if len(combined) < 15:
            raise ValueError(
                "Please provide at least 15 characters across the manuscript title and abstract."
            )
        return self


class RecommendDealSummary(BaseModel):
    """Active institutional deal metadata attached to a recommended journal."""

    publisher_name: str | None = None
    duration_text: str | None = None
    is_capped: bool = False
    cap_reached: bool = False
    cap_text: str | None = None
    is_discount_only: bool = False
    summary: str | None = None
    openaccess_nl_url: str | None = None


class RecommendApcDisplay(BaseModel):
    """The shown price (source, currency, price, year; JournalListItem
    explains them) and the OpenAPC paid block (low, high, and the mean of
    the newest paid period) for a recommended journal."""

    source: ApcSource | None = None
    currency: str | None = None
    price: float | None = None
    year: int | None = None
    low: float | None = None
    high: float | None = None
    mean: float | None = None


class RecommendReason(BaseModel):
    """One transparent argumentation point explaining a journal's placement."""

    kind: str
    tone: Literal["positive", "neutral", "warning"]
    label: str
    detail: str


class RecommendedJournal(BaseModel):
    """One ranked journal recommendation with transparent argumentation."""

    rank: int
    issn_l: str
    title: str | None = None
    publisher: str | None = None
    oa_type: OaType
    deal_covered: bool = False
    deal_summary: RecommendDealSummary | None = None
    similarity: float
    match_score: float
    estimated_cost_label: str
    estimated_cost_eur: float | None = None
    apc_display: RecommendApcDisplay | None = None
    funder_fit: FunderFitOut | None = None
    green_oa: str | None = None
    quartile: str | None = None
    twoyr_mean_citedness: float | None = None
    h_index: int | None = None
    works: int = 0
    topics: list[str] = []
    summary: str
    reasons: list[RecommendReason] = []
    relaxed_note: str | None = None


class RecommendResponse(BaseModel):
    """Guided Journal Finder response with strict matches and relaxed fallbacks."""

    recommendations: list[RecommendedJournal]
    alternatives: list[RecommendedJournal]
    candidate_pool_size: int
    strict_match_count: int
    relaxed: bool
    funder_name: str | None = None
    funder_policy_structured: bool = False
    ranking_factors: list[str]


class SimilarJournalItem(BaseModel):
    issn_l: str
    title: str | None
    publisher_name: str | None
    publisher_canonical: str | None = None
    quartile: str | None
    is_oa: bool | None
    deal_covered: bool
    deal_cap_reached: bool = False
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
    """One OpenAPC period of a journal. The euro_* figures cover the paid
    articles only (amount above zero). paid_count and zero_count (€0: an
    agreement paid for the article) split article_count; the rest reported
    no amount. A NULL count or lowest amount belongs to a row migration
    0005 could not split, until the OpenAPC job rebuilds it."""

    period: int
    article_count: int
    paid_count: int | None = None
    zero_count: int | None = None
    euro_min: float | None = None
    euro_max: float | None = None
    euro_mean: float | None = None


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


class OpenaireTopFos(BaseModel):
    subject: str
    works: int


class OpenaireTopFunder(BaseModel):
    funder: str
    works: int


class OpenaireInfo(BaseModel):
    """OpenAIRE cross-check for one journal, over the confirmed-identity
    facts store (openaire_work_facts)."""

    matched_works: int = 0
    # Facts rows carrying a fulltext url / any usage count / the diamond
    # flag.
    with_fulltext: int = 0
    with_usage: int = 0
    diamond_works: int = 0
    # OA-color cross-check vs OpenAlex: rows where both sides state a
    # label, and how many of those disagree (case-insensitive).
    oa_color_total: int = 0
    oa_color_disagree: int = 0
    top_fos: list[OpenaireTopFos] = []
    top_funders: list[OpenaireTopFunder] = []


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
    """Journal metrics over the canonical UT works population (the works
    tab's stats rows, store-enriched per DOI): fwci_avg/fwci_n/retracted
    are the "UT works" tiles. The venue-level OpenAlex numbers stay as
    separately named cross-check fields (openalex_matched, venue_fwci_*,
    venue_retracted, cited_total); the store mixes harvest populations, so
    they are not UT-works numbers. canonical_* describe the same canonical
    population when the works store is reachable (otherwise None)."""

    openalex_matched: int = 0
    venue_fwci_avg: float | None = None
    venue_fwci_n: int = 0
    venue_retracted: int = 0
    cited_total: int = 0
    fwci_avg: float | None = None
    fwci_n: int = 0
    retracted: int = 0
    canonical_total: int | None = None
    canonical_retracted: int | None = None
    canonical_oa: CanonicalOa | None = None


class WorkUtAuthor(BaseModel):
    id: str
    name: str


class WorkUtGroup(BaseModel):
    name: str


class OpenaireProjectOut(BaseModel):
    """One project linked to the work by OpenAIRE (fields may be null)."""

    id: str | None = None
    funder: str | None = None
    code: str | None = None
    acronym: str | None = None


class OpenaireFactsOut(BaseModel):
    """OpenAIRE-derived facts for one work (openaire_work_facts row)."""

    views: int | None = None
    downloads: int | None = None
    oa_url: str | None = None
    license: str | None = None
    oa_color: str | None = None
    diamond: bool = False
    embargo_end: date | None = None
    fos: list[str] = []
    projects: list[OpenaireProjectOut] = []


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
    # work_type is the canonical (Pure) type; in_openalex marks whether the
    # DOI matched a store row (OpenAlex metrics available).
    work_type: str | None = None
    in_openalex: bool | None = None
    # The work's Pure authors (roster order) and their research groups.
    ut_authors: list[WorkUtAuthor] = []
    ut_groups: list[WorkUtGroup] = []
    # OpenAIRE-derived facts; None when the work has no confirmed
    # openaire identity (no facts row).
    openaire: OpenaireFactsOut | None = None


class WorksPage(BaseModel):
    items: list[WorkItem]
    total: int
    page: int
    page_size: int


class GreenOaRoute(BaseModel):
    """One self-archiving route (per article version) as aggregated by the
    Jisc normalizer from publisher_policy[].permitted_oa."""

    locations: list[str] = []
    repositories: list[str] = []
    licenses: list[str] = []
    embargo_months: int | None = None
    conditions: list[str] = []
    additional_oa_fee: str | None = None


class GreenOaPolicy(BaseModel):
    """Jisc Open Policy Finder green-OA policy bundle (journals.jisc_policy
    display object + stamp columns); null when the journal was never swept."""

    in_opf: bool
    oa_prohibited: bool | None = None
    routes: dict[str, GreenOaRoute] = {}
    internal_moniker: str | None = None
    urls: list[dict[str, str]] = []
    # Route repository short name -> jisc_repositories url; names the
    # normalizer could not match are absent (frontend keeps them plain).
    repository_links: dict[str, str] = {}
    policy_uri: str | None = None
    harvested_at: datetime | None = None


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
    # Open Access NL deals-profile slug of the journal's (canonical)
    # publisher; None when the publisher is not in their registry.
    openaccess_nl_slug: str | None = None
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
    green_oa: GreenOaPolicy | None = None
    # Present only when the detail query passes ?funder=<jisc funder id>.
    funder_fit: FunderFitOut | None = None
    institution_metrics: InstitutionMetrics
    # Who at this institution authors the journal's canonical works.
    ut_authorship: UTAuthorship
    # Store works in this journal missing from the Pure population.
    openalex_only: OpenalexOnly
    attribution: dict[str, Attribution] = {}
