"""Pydantic response schemas for the API (openapi-typescript feeds on these)."""

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .vocab import (
    ApcSource,
    DealJournalSource,
    DealStatus,
    FeedbackCategory,
    FeedbackPriority,
    FeedbackStatus,
    HarvestStatus,
    IdentityStatus,
    OaType,
    WorkIdentityStatus,
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


class FunderListItem(BaseModel):
    id: int
    name: str | None
    country: str | None
    url: str | None
    ror: str | None
    fundref: str | None
    # ROR-preferred link into openalex_funders; None when neither id links.
    openalex_funder_id: str | None = None
    policy_structured: bool = False
    # Normalized JISC OPF requirement levels (requires / encourages /
    # no_policy_for / does_no_mention) extracted from publications_policy and
    # data_archiving_policy.
    oa_publishing_req: str | None = None
    green_archiving_req: str | None = None
    data_policy_req: str | None = None
    # UT works crediting this funder (work_funders); 0 before migration 0049
    # lands or the harvest runs.
    n_ut_works: int = 0


class FunderSearchResponse(BaseModel):
    items: list[FunderListItem]
    total: int
    facets: dict[str, dict[str, int]] = {}


class FunderTopJournal(BaseModel):
    title: str | None
    issn_l: str | None
    n_works: int


class FunderOpenaireStream(BaseModel):
    """One funding level-0 stream with its OpenAIRE project count."""

    level0_id: str
    name: str | None = None
    n_projects: int


class FunderOpenaireBlock(BaseModel):
    """OpenAIRE graph identity for the same funder (canon-linked via ROR)."""

    openaire_id: str
    name: str | None = None
    short_name: str | None = None
    jurisdiction: str | None = None
    website_url: str | None = None
    # Top funding streams by project count (empty before the streams
    # harvest runs).
    streams: list[FunderOpenaireStream] = []


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


class FunderDetailResponse(FunderListItem):
    publications_policy: dict[str, Any] | None = None
    data_archiving_policy: dict[str, Any] | None = None
    openaire: FunderOpenaireBlock | None = None
    top_journals: list[FunderTopJournal] = []
    works_by_year: list[StatsYear] = []


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
    journal_count: int = 0
    # Observed APC spend for the institution's works in the deal's
    # effective journal list (latest-period evidence per DOI, mirror of
    # orgunit APC aggregation).
    apc_euro_total: float = 0.0
    apc_n: int = 0


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
    # max timestamps (or year/period maxima for yearly tables)
    tables: dict[str, Any] = {}
    degraded: list[DegradedSource] = []


# ── Author browsing (ut-metadata ingest) ───────────────────────────────────


class AuthorFacet(BaseModel):
    value: str
    count: int


class AuthorItem(BaseModel):
    pure_uuid: str
    name: str
    faculty: str | None
    research_group: str | None
    institute: str | None
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


class AuthorPeopleProfile(BaseModel):
    """people.utwente.nl profile linked to the author: uuid-verified via
    the profile's research.utwente.nl portal link, or an admin-promoted
    name match. has_photo gates the avatar endpoint URL."""

    slug: str
    url: str
    canonical_name: str | None
    email: str | None
    orgs: list[str]
    faculty_abbr: str | None
    has_photo: bool


class AuthorOut(BaseModel):
    pure_uuid: str
    name: str
    orcid: str | None
    openalex_author_id: str | None
    openaire_person_id: str | None
    crossref_orcid: str | None
    faculty: str | None
    research_group: str | None
    institute: str | None
    orgs: list[str]
    n_works: int
    people: AuthorPeopleProfile | None = None
    # The author's public Pure portal page: the people profile's own
    # link, else constructed when portal persons listings carry the
    # author (portal visibility), else None.
    research_portal_url: str | None = None


class AuthorYearRow(BaseModel):
    year: int
    total: int
    gold: int
    green: int
    hybrid: int
    bronze: int
    closed: int
    diamond: int = 0


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
    # None for OpenAlex-only works: attributed via OpenAlex authorships but
    # absent from the Pure population, so no JB work row exists.
    pure_uuid: str | None = None
    title: str
    year: int
    doi: str | None
    oa_status: str | None
    # Raw works.work_type (e.g. 'info:eu-repo/semantics/bookPart'); the
    # frontend normalizes it into a plain label.
    work_type: str | None = None
    journal_issn_l: str | None
    journal_title: str | None
    # Pure public record page; None when the institution has no portal URL.
    pure_url: str | None = None
    # Matching openalex_works record (same institution, same normalized
    # DOI, lowest w_id); None without a DOI or store row.
    openalex_url: str | None = None
    in_pure: bool = True
    # Where oa_status came from: OpenAlex sync (DOI-matched) or Pure's own
    # access flag (DOI-less rows, where the venue's OA model is unknown).
    oa_status_source: Literal["openalex", "pure"] = "openalex"


class AuthorOpenalexOnlyWork(BaseModel):
    """One OpenAlex-only (missed) work in the author page's dedicated
    section: same gates the merged works list used to apply, but the list
    is the section's own — never truncated by the works cap."""

    pure_uuid: str | None = None
    title: str | None = None
    year: int | None = None
    doi: str | None = None
    oa_status: str | None = None
    work_type: str | None = None
    journal_issn_l: str | None = None
    journal_title: str | None = None
    publisher_name: str | None = None
    openalex_id: str | None = None
    openalex_url: str | None = None
    in_pure: bool = False
    ut_authors: list[UtAuthorAttribution] = []
    # Work parts (OpenAlex, Nov 2026): compact parent works and the
    # is_part flag — chapter of a book when a parent has rel=volume.
    parent_works: list[WorkParent] = []
    is_part: bool = False
    # Why the row is not truly missing from Pure, when a record was
    # identified; None = likely missing. pure_match_url is that record's
    # public page (None without a portal URL).
    pure_match: Literal["doi_in_pure", "parent_book_in_pure", "same_title_in_pure"] | None = None
    pure_match_url: str | None = None


class AuthorOpenalexOnlySingle(AuthorOpenalexOnlyWork):
    """One standalone gap work (no parent works): all work-row fields at
    the top level."""

    kind: Literal["single"] = "single"


class AuthorOpenalexOnlyGroup(BaseModel):
    """One main work with its missing parts (only missing works are
    listed); the parent itself may well be registered."""

    kind: Literal["group"] = "group"
    parent: GapGroupParent
    parts: list[AuthorOpenalexOnlyWork] = []
    parts_total: int = 0


AuthorOpenalexOnlyEntry = Annotated[
    AuthorOpenalexOnlySingle | AuthorOpenalexOnlyGroup, Field(discriminator="kind")
]


class AuthorOpenalexOnly(BaseModel):
    """The author's OpenAlex-only works as their own section: total is
    exact, items hold the grouped entries (missing parts under their main
    work), safety-capped at the entry level; entries_total counts entries
    before the cap."""

    total: int = 0
    entries_total: int = 0
    items: list[AuthorOpenalexOnlyEntry] = []
    available: bool = True
    # Gated rows with no pure_match: the ones likely missing for real.
    likely_missing: int = 0


class PartnerSummary(BaseModel):
    """Compact partner rollup shown on org-unit and author detail pages."""

    ror: str
    name: str
    org_type: str | None = None
    country_code: str | None = None
    city: str | None = None
    works: int
    oa_share: float | None = None


class AuthorProfileResponse(BaseModel):
    author: AuthorOut
    oa_by_year: list[AuthorYearRow]
    journals: list[AuthorJournalRow]
    topics: list[AuthorTopicRow]
    similar: AuthorSimilarBundle
    alternatives: list[AuthorAlternative]
    works: list[AuthorWorkItem]
    top_partners: list[PartnerSummary] = []
    openalex_only: AuthorOpenalexOnly = AuthorOpenalexOnly()
    # Exact count of OpenAlex-only works after gating; None when the
    # source could not answer (DSN path). The openalex_only section
    # carries the works themselves.
    openalex_only_count: int | None = None


# ── Publisher browsing (journals grouped per publisher_name) ───────────────


class TopicMassRow(BaseModel):
    name: str
    n: float


class PublisherApcSummary(BaseModel):
    n_journals: int
    eur_min: float | None = None
    eur_max: float | None = None


class PublisherExternalIds(BaseModel):
    """External registry references for the publisher. Populated on the
    detail payload only; search items leave the defaults in place."""

    # Open Access NL publisher profile slug
    # (openaccess.nl/en/publisher/{slug}); None when the publisher is not
    # in their deals overview.
    openaccess_nl_slug: str | None = None
    # ROR registration url as harvested from jisc_publishers
    # ("https://ror.org/<id>"); None when no OPF row with a ROR id
    # matches the publisher by name.
    ror: str | None = None


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
    external_ids: PublisherExternalIds = PublisherExternalIds()


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
    # Who at this institution authors the group's canonical works.
    ut_authorship: UTAuthorship
    # Store works in the group's journals missing from the Pure population.
    openalex_only: OpenalexOnly
    # Chapter/book rollup over the same gap population (before the list
    # cap): chapter-kind works and their volume parents.
    chapter_rollup: PartsRollup


# ── Org-unit browsing (faculties + research groups) ────────────────────────


class OrgUnitItem(BaseModel):
    level: Literal["faculty", "group", "institute"]
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
    # Share (0..1) of the author's counted works whose OA status is
    # diamond or gold; None below the 4-work ranking minimum (such rows
    # sort after all ranked authors in the share ordering).
    oa_diamond_gold_share: float | None = None


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
    top_partners: list[PartnerSummary] = []
    # Store works attributed to the unit's member authors and missing
    # from the Pure population.
    openalex_only: OpenalexOnly
    # Chapter/book rollup over the same gap population (before the card's
    # item cap): chapter-kind works and their volume parents.
    chapter_rollup: PartsRollup


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

    Serves the identity review drawer from the harvest's verbatim payloads
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


class OpsFreshnessEntryOut(BaseModel):
    """Latest harvest state per (source, entity_type)."""

    source: str
    entity_type: str
    status: str
    finished_at: datetime | None


class AdminOpsStatusOut(BaseModel):
    """Ops dashboard payload (GET /admin/ops/status)."""

    generated_at: datetime
    last_wave: OpsLastWaveOut | None
    schedules: list[OpsScheduleOut]
    backup: OpsBackupOut
    freshness: list[OpsFreshnessEntryOut]
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


# ── Collaborations (/collaborations) ───────────────────────────────────────


class FacetCount(BaseModel):
    """One facet value and the number of works in the result set that
    match it."""

    value: str
    label: str | None = None
    count: int


class CollaborationFunder(BaseModel):
    """A funder credited on the joint works. OpenAlex awards and OpenAIRE
    projects that credit the same funder are one entry."""

    # Filter key: "openalex:<bare OpenAlex funder id>" for a funder OpenAlex
    # knows, "openaire:<funder name as the project payload gives it>" for a
    # funder only OpenAIRE names.
    key: str
    # The name as OpenAlex gives it when OpenAlex credits the funder.
    name: str
    # Payloads that credit the funder on the selected works.
    sources: list[Literal["openalex", "openaire"]]
    works: int
    # Jisc OPF funder id when canon-linked, so the UI can link to /funders/{id}.
    jisc_funder_id: int | None = None


class CollaborationProject(BaseModel):
    """A grant or project acknowledged on the joint works."""

    # Filter key: "openalex:<bare funder id>/<grant code>" when resolved to a
    # known OpenAlex funder + code, else "openaire:<OpenAIRE project id>".
    key: str
    code: str | None = None
    acronym: str | None = None
    # Funder name as the payload gives it.
    funder: str | None = None
    source: Literal["openalex", "openaire"]
    sources: list[Literal["openalex", "openaire"]] = []
    works: int


class CollaborationPartner(BaseModel):
    """A partner institution in the list or the detail view."""

    ror: str
    name: str
    org_type: str | None = None
    country_code: str | None = None
    city: str | None = None
    lat: float | None = None
    lng: float | None = None
    parent_ror: str | None = None
    parent_name: str | None = None
    # False when ROR has no record for this id and the name comes from
    # the work payload alone.
    in_ror: bool
    works: int
    # works / total_works in the result set; None when the set is empty.
    share: float | None = None
    corresponding_works: int
    # Joint works where the home institution holds a corresponding author.
    home_corresponding_works: int = 0
    # Author positions held at the partner across the joint works.
    authorships: int
    # Joint works with an open access status (gold/diamond/hybrid/green/bronze).
    oa_works: int = 0
    closed_works: int = 0
    oa_share: float | None = None
    # True when the partner participates in at least one OA deal shared with
    # the home institution (via deal_institutions).
    shares_deals: bool = False
    # Number of rolled-up child/inactive RORs folded into this partner when
    # rollup is enabled.
    merged_count: int = 0
    # Payloads that supplied the links to this partner.
    sources: list[Literal["openalex", "openaire"]]
    funders: list[CollaborationFunder] = []
    projects: list[CollaborationProject] = []


class CollaborationFacets(BaseModel):
    """Facet values under every active filter except the facet's own
    dimension. Every count is a number of works in that result set."""

    org_type: list[FacetCount]
    country: list[FacetCount]
    orgunit: list[FacetCount]
    funder: list[CollaborationFunder]
    project: list[CollaborationProject]
    source: list[FacetCount]
    oa_status: list[FacetCount] = []
    topic: list[FacetCount] = []


class CollaborationTrendYear(BaseModel):
    """Per-year aggregate of collaborative works for the overview chart."""

    year: int
    total_works: int
    with_partner: int
    domestic: int
    international: int
    oa_gold: int = 0
    oa_diamond: int = 0
    oa_hybrid: int = 0
    oa_green: int = 0
    oa_bronze: int = 0
    oa_closed: int = 0
    # Collaborative works with at least one partner of each ROR organisation
    # type ("unknown" when ROR has no type). A work with partners of two
    # types counts under both, so the values can sum to more than
    # with_partner.
    by_org_type: dict[str, int] = {}


class CollaborationSearchResponse(BaseModel):
    items: list[CollaborationPartner]
    total_partners: int
    # Works of the institution in the filtered set, with or without a
    # partner link.
    total_works: int
    # Of those, works linked to at least one partner.
    works_with_partner: int
    # Works linked to at least one domestic vs international partner.
    domestic_works: int = 0
    international_works: int = 0
    # Open access vs closed works among works_with_partner.
    oa_works: int = 0
    closed_works: int = 0
    # Works linked to at least one partner through each payload.
    works_by_source: dict[Literal["openalex", "openaire"], int]
    # Effective publication-year range; None when the set has no works.
    year_from: int | None = None
    year_to: int | None = None
    trend: list[CollaborationTrendYear] = []
    facets: CollaborationFacets | None = None


class CollaborationMapPoint(BaseModel):
    """One partner with coordinates, for the map."""

    ror: str
    name: str
    country_code: str | None = None
    city: str | None = None
    # ROR organisation type in lower case; "unknown" when ROR gives none.
    org_type: str
    lat: float
    lng: float
    works: int
    corresponding_works: int
    home_corresponding_works: int = 0
    oa_share: float | None = None
    merged_count: int = 0


class CollaborationMapResponse(BaseModel):
    items: list[CollaborationMapPoint]
    # Partners in the filtered set without coordinates; they do not
    # appear on the map.
    unmapped: int


class CollaborationWorkAuthor(BaseModel):
    """An institution author on a joint work, linked when on the roster."""

    pure_uuid: str | None = None
    name: str


class CollaborationWork(BaseModel):
    """One joint work: by the institution and the partner."""

    pure_uuid: str
    title: str
    year: int
    # Normalized DOI ("10.1000/xyz123"); None when the work has none.
    doi: str | None = None
    work_type: str | None = None
    # A corresponding author sits at the partner.
    corresponding: bool
    # A corresponding author sits at the home institution.
    home_corresponding: bool = False
    oa_status: str | None = None
    journal_issn_l: str | None = None
    journal_title: str | None = None
    deal_covered: bool = False
    # Payload that supplied the link to the partner.
    source: Literal["openalex", "openaire"]
    # Display names of the institution's authors on the work.
    authors: list[str]
    author_links: list[CollaborationWorkAuthor] = []


class CollaborationYearCount(BaseModel):
    year: int
    works: int
    oa_gold: int = 0
    oa_diamond: int = 0
    oa_hybrid: int = 0
    oa_green: int = 0
    oa_bronze: int = 0
    oa_closed: int = 0


class CollaborationLink(BaseModel):
    """An identifier or URL the ROR record lists for the partner."""

    type: str
    value: str


class CollaborationRelation(BaseModel):
    """A parent, child, or related organisation in the ROR record."""

    type: str
    ror: str
    label: str
    # True when this related organisation is also a partner of the institution.
    is_partner: bool = False


class CollaborationUnitCount(BaseModel):
    """Home-institution org unit collaborating with a partner."""

    name: str
    level: Literal["faculty", "group", "institute"]
    works: int


class CollaborationAuthorCount(BaseModel):
    """Home-institution researcher collaborating with a partner."""

    pure_uuid: str
    name: str
    faculty: str | None = None
    research_group: str | None = None
    works: int


class CollaborationJournalCount(BaseModel):
    """Shared publication venue between the institution and a partner."""

    issn_l: str
    title: str
    works: int
    closed_works: int = 0
    oa_type: str | None = None
    quartile: str | None = None
    deal_covered: bool = False


class CollaborationMergedChild(BaseModel):
    """A child or inactive ROR rolled up into this partner."""

    ror: str
    name: str
    status: str | None = None
    works: int


class CollaborationDetailResponse(CollaborationPartner):
    status: str | None = None
    openalex_id: str | None = None
    # ROR display name, labels, acronyms and aliases, deduplicated.
    labels: list[str]
    links: list[CollaborationLink]
    relationships: list[CollaborationRelation]
    # Works of the institution in the filtered set (the share denominator).
    total_works: int
    # Closed joint works published in a journal covered by a home-institution deal.
    deal_closed_works: int = 0
    # Normalized work types of the joint works (article, conference, ...).
    works_by_type: list[FacetCount]
    # Joint works per publication year inside the filtered range (with OA mix).
    per_year: list[CollaborationYearCount]
    # Home-institution faculties, research groups and authors on the joint works.
    ut_faculties: list[CollaborationUnitCount] = []
    ut_groups: list[CollaborationUnitCount] = []
    ut_authors: list[CollaborationAuthorCount] = []
    # Top shared journals and OpenAlex primary topics.
    top_journals: list[CollaborationJournalCount] = []
    top_topics: list[FacetCount] = []
    # Child/inactive RORs folded into this partner when rollup is enabled.
    merged_children: list[CollaborationMergedChild] = []
    # Joint works by payload, newest first, capped at 25 (when include_works=True).
    recent_works: list[CollaborationWork] = []


class CollaborationWorksResponse(BaseModel):
    items: list[CollaborationWork]
    total: int
