"""Funder, author, publisher, and org-unit Pydantic schemas."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from .common import (
    DealOut,
    GapGroupParent,
    OpenalexOnly,
    PartnerSummary,
    PartsRollup,
    StatsYear,
    TopicMassRow,
    UtAuthorAttribution,
    UTAuthorship,
    WorkParent,
)
from .journals import JournalListItem


class FunderListItem(BaseModel):
    id: int
    name: str | None
    country: str | None
    url: str | None
    ror: str | None
    fundref: str | None
    # Bare OpenAlex id ("F4320320300") of the linked funder the
    # institution's works cite most; None when neither id links.
    openalex_funder_id: str | None = None
    policy_structured: bool = False
    # Normalized JISC OPF requirement levels (requires / encourages /
    # no_policy_for / does_not_mention) extracted from publications_policy and
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


class FunderDetailResponse(FunderListItem):
    publications_policy: dict[str, Any] | None = None
    data_archiving_policy: dict[str, Any] | None = None
    openaire: FunderOpenaireBlock | None = None
    top_journals: list[FunderTopJournal] = []
    works_by_year: list[StatsYear] = []


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
    # Which field q matched: "name", or the fallback that fired when no
    # name matched ("topic" = primary_topic, "group" = research_group);
    # "name" without a q. The UI labels topic/group result sets.
    q_match: Literal["name", "topic", "group"] = "name"
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
