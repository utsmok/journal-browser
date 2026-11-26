"""Collaboration partner Pydantic schemas."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from .common import FacetCount


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


# One partner with coordinates, sent as a row: the map holds about 9,000
# of them and object keys were more than half of the payload. Fields in
# order: ror, name, country_code, city, org_type, lat, lng, works,
# corresponding_works, home_corresponding_works, oa_share. org_type is the
# ROR organisation type in lower case ("unknown" when ROR gives none);
# oa_share is 0 to 1 rounded to four decimals, None without works.
CollaborationMapPoint = Annotated[
    tuple[str, str, str | None, str | None, str, float, float, int, int, int, float | None],
    Field(
        min_length=11,
        max_length=11,
        description=(
            "(ror, name, country_code, city, org_type, lat, lng, works, "
            "corresponding_works, home_corresponding_works, oa_share)"
        ),
    ),
]


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
