"""Collaboration partners: counts, facets, overview trends and detail for
/collaborations, plus compact partner summaries for org-unit and author pages.

work_partners holds one link per work and partner ROR id. The derive job
(harvest.work_partners) rebuilds it from stored OpenAlex and OpenAIRE work
payloads. partner_institutions holds the ROR records, searchable aliases,
and conservative parent/successor roll-up pointers (rollup_ror).

Every number here counts works, never raw links: a work with three partners
counts once in the totals and once under each of its partners. When rollup is
enabled (default), child/inactive RORs fold into their canonical partner and
links are deduplicated per (work, canonical partner) before any count runs.
"""

import re
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from fastapi.responses import StreamingResponse
from sqlalchemy import (
    Numeric,
    Text,
    and_,
    any_,
    case,
    distinct,
    func,
    literal,
    not_,
    or_,
    select,
    union_all,
)
from sqlalchemy import cast as sql_cast
from sqlalchemy.dialects.postgresql import JSONB, aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ..identifiers import bare_openalex_id, normalize_ror
from ..models import (
    Author,
    AuthorWork,
    DealInstitution,
    FunderAlias,
    FunderLink,
    Institution,
    Journal,
    JournalFlags,
    OpenaireWorkFacts,
    OpenalexFunder,
    PartnerInstitution,
    Work,
    WorkFunder,
    WorkPartner,
    WorkPureAuthor,
)
from ..queries import cache_epoch, work_type_normalized, work_type_not_excluded
from ..schemas import (
    CollaborationDetailResponse,
    CollaborationFacets,
    CollaborationFunder,
    CollaborationLink,
    CollaborationMapPoint,
    CollaborationMapResponse,
    CollaborationPartner,
    CollaborationProject,
    CollaborationRelation,
    CollaborationSearchResponse,
    CollaborationTrendYear,
    CollaborationWork,
    CollaborationWorkAuthor,
    CollaborationWorksResponse,
    FacetCount,
)
from .cache import (
    FACET_CACHE,
    SNAPSHOT_TTL,
    SWR_CACHE,
    cache_get,
    cache_put,
    swr_get,
    swr_put,
    swr_schedule,
)
from .collaborations_detail import (
    OA_OPEN_STATUSES,
    STANDARD_MAX_PARTNERS,
    detail_breakdowns,
    primary_topic_expr,
    top_partners_for_author,
    top_partners_for_orgunit,
)
from .concurrency import together
from .csv_export import csv_response, csv_safe, safe_filename
from .works_query import (
    YEAR_BUCKETS,
    unit_key,
    unit_work_conditions,
    work_window,
)

__all__ = [
    "CollaborationFilters",
    "collaboration_detail",
    "collaboration_map",
    "collaborations_csv",
    "collaborations_trend_csv",
    "partner_works",
    "partner_works_csv",
    "search_collaborations",
    "top_partners_for_author",
    "top_partners_for_orgunit",
]

FACET_CAP = 100
ITEM_LIST_CAP = 5
DETAIL_LIST_CAP = 25
RECENT_WORKS = 25
AUTHOR_CAP = 50
SMALL_MAX_PARTNERS = 5
#: sessions _together uses at once, on top of the request's own session
QUERY_CONCURRENCY = 4

_Payload = Literal["openalex", "openaire"]
_SizeMode = Literal["standard", "small", "all"]
_LeadMode = Literal["all", "home", "partner"]

#: Grant values that are not grant numbers, matched by shape. Each pattern
#: is one kind of value publishers put in the award field instead.
_YEAR = r"(?:19|20)[0-9]{2}"
#: A year or a span of years, the funding period: "2007–2013", "2021 2027",
#: "2004.".
_YEAR_OR_SPAN = (
    r"^\(?" + _YEAR + r"\)?"
    r"(?:\s*[^0-9a-z]{1,6}\s*\(?" + _YEAR + r"\)?){0,2}[,.;]?$"
)
#: A programme label, one or more words followed by a year: "HORIZON2020",
#: "Horizon 2020", "France2030".
_PROGRAMME_LABEL = r"^(?:[a-z]+\s?)+" + _YEAR + r"$"

_PARTNER_CSV = (
    "ror",
    "name",
    "org_type",
    "country_code",
    "city",
    "works",
    "home_corresponding_works",
    "corresponding_works",
    "authorships",
    "oa_works",
    "closed_works",
    "oa_share",
    "shares_deals",
    "share",
    "sources",
    "funders",
    "projects",
)
# ROR organisation types in the column order of the trend CSV; "unknown"
# covers partners whose ROR record has no type.
_ORG_TYPES = (
    "education",
    "healthcare",
    "facility",
    "government",
    "company",
    "nonprofit",
    "funder",
    "archive",
    "other",
    "unknown",
)
_TREND_CSV = (
    "year",
    "all_works",
    "collaborative_works",
    "collaborative_share",
    "domestic_works",
    "international_works",
    "oa_works",
    "closed_works",
    *(f"{kind}_{col}" for kind in _ORG_TYPES for col in ("works", "share")),
)
_WORK_CSV = (
    "pure_uuid",
    "title",
    "year",
    "doi",
    "work_type",
    "journal",
    "oa_status",
    "deal_covered",
    "home_corresponding",
    "corresponding",
    "source",
    "authors",
)


@dataclass(frozen=True, slots=True)
class CollaborationFilters:
    """Every list, map, detail, works and export filter in one object.
    Multi-select fields are OR'ed within their dimension and AND'ed across
    dimensions; None means the dimension is not filtered.
    """

    q: str | None = None
    org_types: Sequence[str] | None = None
    countries: Sequence[str] | None = None
    level: str = "faculty"
    faculty: Sequence[str] | None = None
    funders: Sequence[str] | None = None
    projects: Sequence[str] | None = None
    sources: Sequence[str] | None = None
    oa_statuses: Sequence[str] | None = None
    topics: Sequence[str] | None = None
    size: _SizeMode = "standard"
    rollup: bool = True
    lead: _LeadMode = "all"
    min_works: int | None = None
    shares_deals: bool | None = None
    year_range: tuple[int, int] | None = None


def _payload(value: Any) -> _Payload:
    return "openaire" if value == "openaire" or str(value).startswith("openaire:") else "openalex"


def _sources(values: Sequence[str] | None) -> list[_Payload]:
    return [_payload(value) for value in sorted(values or [])]


def _primary_topic() -> Any:
    return primary_topic_expr()


def _valid_project_code(col: Any) -> Any:
    """SQL expression returning a cleaned grant code, or NULL when the
    value is not one. Four shapes are dropped, each a value publishers put
    in the award field instead of a grant number: a word or placeholder
    with no digit other than zero (OpenAIRE "unidentified", "COMPETE",
    "0000"); a year or a span of years ("2007–2013", "2021 2027"); a
    programme label ("HORIZON2020", "France2030"); a funding
    acknowledgement carrying a Funder Registry DOI
    ("MCIN/AEI/10.13039/501100011033").

    The label pattern also takes grant numbers whose digits happen to be
    a year (DFG "GRK 2073", JST "JPMJCR2014"): about 50 of 43,500 stored
    awards on 2026-11-24, against about 1,250 programme labels. A short
    ordinal such as "FP7" cannot be told from grant numbers like FWF
    "Y 42" and passes."""
    trimmed = func.nullif(func.btrim(col), "")
    is_code = and_(
        trimmed.op("~")("[1-9]"),
        not_(trimmed.op("~*")(_YEAR_OR_SPAN)),
        not_(trimmed.op("~*")(_PROGRAMME_LABEL)),
        not_(func.lower(trimmed).contains("10.13039/")),
    )
    return case((is_code, trimmed), else_=None)


async def _shared_deal_rors(session: AsyncSession, institution: Institution) -> frozenset[str]:
    """Bare ROR ids of organisations that participate in at least one OA deal
    shared with `institution`, cached per harvest epoch."""
    key = ("collab_deal_rors", institution.id, await cache_epoch(session))
    hit = cache_get(FACET_CACHE, key, SNAPSHOT_TTL)
    if hit is not None:
        return hit
    home_deals = select(DealInstitution.deal_id).where(
        DealInstitution.institution_id == institution.id
    )
    rows = (
        await session.execute(
            select(Institution.ror)
            .distinct()
            .join(DealInstitution, DealInstitution.institution_id == Institution.id)
            .where(
                DealInstitution.deal_id.in_(home_deals),
                Institution.id != institution.id,
                Institution.ror.is_not(None),
            )
        )
    ).scalars()
    rors = frozenset(r for raw in rows if (r := normalize_ror(raw)) is not None)
    cache_put(FACET_CACHE, key, rors)
    return rors


async def _merged_counts(session: AsyncSession) -> dict[str, int]:
    """Number of rolled-up child/inactive RORs per canonical target ROR."""
    key = ("collab_merged_counts", await cache_epoch(session))
    hit = cache_get(FACET_CACHE, key, SNAPSHOT_TTL)
    if hit is not None:
        return hit
    rows = (
        await session.execute(
            select(PartnerInstitution.rollup_ror, func.count())
            .where(PartnerInstitution.rollup_ror.is_not(None))
            .group_by(PartnerInstitution.rollup_ror)
        )
    ).all()
    counts = {str(ror): int(n) for ror, n in rows}
    cache_put(FACET_CACHE, key, counts)
    return counts


async def _jisc_funder_map(session: AsyncSession) -> dict[str, int]:
    """Bare OpenAlex funder id -> Jisc OPF funder_id for internal links."""
    key = ("collab_jisc_funder_map", await cache_epoch(session))
    hit = cache_get(FACET_CACHE, key, SNAPSHOT_TTL)
    if hit is not None:
        return hit
    rows = (
        await session.execute(
            select(FunderLink.source_id, func.min(FunderLink.funder_id))
            .where(FunderLink.source == "openalex")
            .group_by(FunderLink.source_id)
        )
    ).all()
    mapping = {str(sid).rsplit("/", 1)[-1]: int(fid) for sid, fid in rows if sid}
    cache_put(FACET_CACHE, key, mapping)
    return mapping


async def _home_country(session: AsyncSession, institution: Institution) -> str | None:
    """ISO alpha-2 country code of the home institution (for domestic vs
    international splits)."""
    home_ror = normalize_ror(institution.ror)
    if home_ror:
        cc = await session.scalar(
            select(PartnerInstitution.country_code).where(PartnerInstitution.ror == home_ror)
        )
        if cc:
            return str(cc).upper()
    if institution.library_url and ".nl" in institution.library_url.lower():
        return "NL"
    return None


# --- condition builders ---------------------------------------------------


def _awards(institution: Institution) -> Any:
    """One row per OpenAlex funder credit on the institution's works:
    funder_key openalex:<bare id>, project_key openalex:<bare id>/<CODE>."""
    funder_id = bare_openalex_id(WorkFunder.funder_openalex_id)
    award = _valid_project_code(WorkFunder.award)
    return (
        select(
            WorkFunder.pure_uuid.label("work"),
            func.concat("openalex:", funder_id).label("funder_key"),
            func.coalesce(OpenalexFunder.display_name, WorkFunder.funder_name, funder_id).label(
                "funder_name"
            ),
            case(
                (award.is_not(None), func.concat("openalex:", funder_id, "/", func.upper(award)))
            ).label("project_key"),
            award.label("code"),
            sql_cast(literal(None), Text).label("acronym"),
            literal("openalex", Text).label("payload"),
        )
        .outerjoin(OpenalexFunder, OpenalexFunder.openalex_id == funder_id)
        .where(WorkFunder.institution_id == institution.id)
        .subquery()
    )


def _projects(institution: Institution) -> Any:
    """One row per OpenAIRE project credit on the institution's works.
    When funder_aliases resolves the funder to an OpenAlex id and a valid
    grant code is present, project_key uses the same canonical
    openalex:<bare id>/<CODE> key as _awards so identical grants merge."""
    elements = (
        select(
            OpenaireWorkFacts.pure_uuid.label("work"),
            sql_cast(func.jsonb_array_elements(OpenaireWorkFacts.projects), JSONB).label("project"),
        )
        .where(OpenaireWorkFacts.institution_id == institution.id)
        .subquery()
    )
    project = elements.c.project

    def value(key: str) -> Any:
        return func.nullif(func.btrim(project[key].astext), "")

    funder = value("funder")
    pid = value("id")
    raw_code = value("code")
    code = _valid_project_code(raw_code)
    acronym = value("acronym")
    resolved = FunderAlias.funder_openalex_id
    # Drop OpenAIRE entries whose code is not a grant number (OpenAIRE
    # "unidentified") and that carry no acronym.
    is_junk_only = and_(raw_code.is_not(None), code.is_(None), acronym.is_(None))
    project_key = case(
        (is_junk_only, None),
        (
            and_(resolved.is_not(None), code.is_not(None)),
            func.concat("openalex:", resolved, "/", func.upper(code)),
        ),
        (pid.is_not(None), func.concat("openaire:", pid)),
    )
    return (
        select(
            elements.c.work,
            case(
                (resolved.is_not(None), func.concat("openalex:", resolved)),
                (funder.is_not(None), func.concat("openaire:", funder)),
            ).label("funder_key"),
            func.coalesce(OpenalexFunder.display_name, funder).label("funder_name"),
            project_key.label("project_key"),
            code.label("code"),
            acronym.label("acronym"),
            literal("openaire", Text).label("payload"),
        )
        .select_from(elements)
        .outerjoin(FunderAlias, FunderAlias.funder_name == funder)
        .outerjoin(OpenalexFunder, OpenalexFunder.openalex_id == resolved)
        .subquery()
    )


def _credit_sources(institution: Institution) -> list[tuple[_Payload, Any]]:
    return [("openalex", _awards(institution)), ("openaire", _projects(institution))]


def _credits(institution: Institution, dimension: str) -> Any:
    """Both payloads' credits of one dimension (funder or project) in one
    subquery: work, key, name, code, acronym, payload."""
    key = f"{dimension}_key"
    return union_all(
        *(
            select(
                source.c.work,
                source.c[key].label("key"),
                source.c.funder_name.label("name"),
                source.c.code,
                source.c.acronym,
                source.c.payload,
            )
            for _, source in _credit_sources(institution)
        )
    ).subquery()


def _credit_name(credits: Any) -> Any:
    return func.coalesce(
        func.max(case((credits.c.payload == "openalex", credits.c.name))),
        func.max(credits.c.name),
    )


def _credit_sources_list(credits: Any) -> Any:
    return func.array_agg(distinct(credits.c.payload))


def _work_conditions(
    institution: Institution, filters: CollaborationFilters, *, drop: str | None = None
) -> list[Any]:
    conds: list[Any] = [
        Work.institution_id == institution.id,
        Work.retired_at.is_(None),
        work_type_not_excluded(Work.work_type),
    ]
    if drop != "years":
        if filters.year_range is None:
            conds.extend(work_window(institution))
        else:
            lo, hi = filters.year_range
            conds.extend((Work.year >= lo, Work.year <= hi))
    if drop != "orgunit" and filters.faculty:
        conds.append(
            select(AuthorWork.work_pure_uuid)
            .join(Author, Author.pure_uuid == AuthorWork.author_pure_uuid)
            .where(*unit_work_conditions(institution, filters.level, filters.faculty))
            .exists()
        )
    if drop != "oa_status" and filters.oa_statuses:
        conds.append(func.lower(Work.oa_status).in_([v.lower() for v in filters.oa_statuses]))
    if drop != "topic" and filters.topics:
        conds.append(
            Work.journal_issn_l.in_(
                select(Journal.issn_l).where(_primary_topic().in_(list(filters.topics)))
            )
        )
    for dimension, column in (("funder", "funder_key"), ("project", "project_key")):
        keys = getattr(filters, f"{dimension}s")
        if drop != dimension and keys:
            conds.append(
                or_(
                    *(
                        Work.pure_uuid.in_(select(source.c.work).where(source.c[column].in_(keys)))
                        for _, source in _credit_sources(institution)
                    )
                )
            )
    return conds


def _link_conditions(filters: CollaborationFilters, *, drop: str | None = None) -> list[Any]:
    conds: list[Any] = []
    if filters.sources and drop != "source":
        conds.append(WorkPartner.source.in_(list(filters.sources)))
    if filters.size == "standard":
        conds.append(WorkPartner.partner_count <= STANDARD_MAX_PARTNERS)
    elif filters.size == "small":
        conds.append(WorkPartner.partner_count <= SMALL_MAX_PARTNERS)
    return conds


def _search_condition(needle: str) -> Any:
    """Match partner ROR, acronyms, ROR aliases, display name and city.
    Short queries (<=4 chars like MST, RUG, MIT, CERN, TNO) require an exact
    acronym or word-start match so they never trigger mid-word false positives
    like 'Amsterdam' for 'mst' or 'Perugia' for 'rug'."""
    haystack = func.coalesce(PartnerInstitution.search_text, func.lower(PartnerInstitution.name))
    if len(needle) <= 4:
        escaped = re.escape(needle)
        pattern = rf"\m{escaped}" if needle[0].isalnum() else escaped
        return or_(
            PartnerInstitution.ror == needle,
            needle == any_(PartnerInstitution.acronyms),
            haystack.op("~*")(pattern),
        )
    return or_(
        PartnerInstitution.ror == needle,
        needle == any_(PartnerInstitution.acronyms),
        haystack.contains(needle, autoescape=True),
    )


def _partner_conditions(
    filters: CollaborationFilters,
    *,
    drop: str | None = None,
    deal_rors: frozenset[str] = frozenset(),
) -> list[Any]:
    """Conditions on PartnerInstitution. The name search is never dropped."""
    conds: list[Any] = []
    needle = (filters.q or "").strip().lower()
    if needle:
        conds.append(_search_condition(needle))
    if filters.org_types and drop != "org_type":
        conds.append(
            func.lower(PartnerInstitution.org_type).in_([v.lower() for v in filters.org_types])
        )
    if filters.countries and drop != "country":
        conds.append(
            func.upper(PartnerInstitution.country_code).in_([v.upper() for v in filters.countries])
        )
    if filters.shares_deals is not None and drop != "shares_deals":
        if filters.shares_deals:
            conds.append(
                PartnerInstitution.ror.in_(sorted(deal_rors)) if deal_rors else literal(False)
            )
        elif deal_rors:
            conds.append(~PartnerInstitution.ror.in_(sorted(deal_rors)))
    return conds


# --- link sets --------------------------------------------------------------


def _links(
    institution: Institution,
    filters: CollaborationFilters,
    *,
    work: str | None = None,
    link: str | None = None,
) -> Any:
    """Subquery with one row per (work, effective ror) passing work-level and
    link-level filters. When rollup=True, child/inactive RORs fold into their
    canonical rollup_ror and multiple rows for the same (work, ror) merge."""
    home_ror = normalize_ror(institution.ror)
    if not filters.rollup:
        stmt = (
            select(
                WorkPartner.work_pure_uuid.label("work"),
                WorkPartner.partner_ror.label("ror"),
                WorkPartner.source.label("source"),
                WorkPartner.corresponding.label("corresponding"),
                WorkPartner.home_corresponding.label("home_corresponding"),
                WorkPartner.authorships.label("authorships"),
            )
            .join(
                Work,
                and_(
                    Work.institution_id == WorkPartner.institution_id,
                    Work.pure_uuid == WorkPartner.work_pure_uuid,
                ),
            )
            .where(
                *_work_conditions(institution, filters, drop=work),
                *_link_conditions(filters, drop=link),
            )
        )
        if filters.lead == "home":
            stmt = stmt.where(WorkPartner.home_corresponding.is_(True))
        elif filters.lead == "partner":
            stmt = stmt.where(WorkPartner.corresponding.is_(True))
        return stmt.subquery()

    raw_pi = aliased(PartnerInstitution)
    eff_ror = func.coalesce(raw_pi.rollup_ror, WorkPartner.partner_ror).label("ror")
    conds = [
        *_work_conditions(institution, filters, drop=work),
        *_link_conditions(filters, drop=link),
    ]
    if home_ror:
        conds.append(func.coalesce(raw_pi.rollup_ror, WorkPartner.partner_ror) != home_ror)
    grouped = (
        select(
            WorkPartner.work_pure_uuid.label("work"),
            eff_ror,
            # "openalex" > "openaire", so max keeps OpenAlex when both occur.
            func.max(WorkPartner.source).label("source"),
            func.bool_or(WorkPartner.corresponding).label("corresponding"),
            func.bool_or(WorkPartner.home_corresponding).label("home_corresponding"),
            func.max(WorkPartner.authorships).label("authorships"),
        )
        .join(
            Work,
            and_(
                Work.institution_id == WorkPartner.institution_id,
                Work.pure_uuid == WorkPartner.work_pure_uuid,
            ),
        )
        .outerjoin(raw_pi, raw_pi.ror == WorkPartner.partner_ror)
        .where(*conds)
        .group_by(WorkPartner.work_pure_uuid, eff_ror)
    )
    if filters.lead == "home":
        grouped = grouped.having(func.bool_or(WorkPartner.home_corresponding).is_(True))
    elif filters.lead == "partner":
        grouped = grouped.having(func.bool_or(WorkPartner.corresponding).is_(True))
    return grouped.subquery()


def _selected(
    institution: Institution,
    filters: CollaborationFilters,
    *,
    work: str | None = None,
    link: str | None = None,
    partner: str | None = None,
    deal_rors: frozenset[str] = frozenset(),
) -> Any:
    """_links reduced to partners passing the partner filters (and optional
    min_works threshold): the exact link set behind every count on the page."""
    links = _links(institution, filters, work=work, link=link)
    base = (
        select(
            links.c.work,
            links.c.ror,
            links.c.source,
            links.c.corresponding,
            links.c.home_corresponding,
            links.c.authorships,
        )
        .join(PartnerInstitution, PartnerInstitution.ror == links.c.ror)
        .where(*_partner_conditions(filters, drop=partner, deal_rors=deal_rors))
        .subquery()
    )
    if filters.min_works and filters.min_works > 1:
        qualifying = (
            select(base.c.ror)
            .group_by(base.c.ror)
            .having(func.count() >= filters.min_works)
            .subquery()
        )
        return (
            select(
                base.c.work,
                base.c.ror,
                base.c.source,
                base.c.corresponding,
                base.c.home_corresponding,
                base.c.authorships,
            )
            .where(base.c.ror.in_(select(qualifying.c.ror)))
            .subquery()
        )
    return base


def _per_partner(institution: Institution, selected: Any) -> Any:
    """One row per partner in `selected` with ROR metadata, work counts,
    corresponding-author split and OA counts."""
    oa_cnt = func.count().filter(Work.oa_status.in_(OA_OPEN_STATUSES))
    total_cnt = func.count()
    return (
        select(
            selected.c.ror.label("ror"),
            func.coalesce(PartnerInstitution.name, selected.c.ror).label("name"),
            PartnerInstitution.org_type,
            PartnerInstitution.country_code,
            PartnerInstitution.city,
            PartnerInstitution.lat,
            PartnerInstitution.lng,
            PartnerInstitution.parent_ror,
            PartnerInstitution.parent_name,
            PartnerInstitution.acronyms,
            PartnerInstitution.payload.is_not(None).label("in_ror"),
            total_cnt.label("works"),
            func.count().filter(selected.c.corresponding).label("corresponding_works"),
            func.count().filter(selected.c.home_corresponding).label("home_corresponding_works"),
            func.sum(selected.c.authorships).label("authorships"),
            oa_cnt.label("oa_works"),
            func.count().filter(Work.oa_status == "closed").label("closed_works"),
            (sql_cast(oa_cnt, Numeric) / func.nullif(sql_cast(total_cnt, Numeric), 0)).label(
                "oa_share"
            ),
            func.array_agg(func.distinct(selected.c.source)).label("sources"),
        )
        .join(
            Work,
            and_(Work.institution_id == institution.id, Work.pure_uuid == selected.c.work),
        )
        .outerjoin(PartnerInstitution, PartnerInstitution.ror == selected.c.ror)
        .group_by(selected.c.ror, PartnerInstitution.ror)
    )


_SORTS = {
    "works": ("works", "name"),
    "name": ("name", "works"),
    "corresponding_works": ("corresponding_works", "works"),
    "home_corresponding_works": ("home_corresponding_works", "works"),
    "oa_share": ("oa_share", "works"),
}


def _ordered(stmt: Any, sort: str, direction: str | None, query_text: str | None = None) -> Any:
    primary, tie = _SORTS[sort]
    descending = (primary != "name") if direction is None else direction == "desc"
    columns = stmt.selected_columns
    first = (
        columns[primary].desc().nulls_last() if descending else columns[primary].asc().nulls_last()
    )
    second = columns[tie].asc() if tie == "name" else columns[tie].desc()
    order_terms: list[Any] = []
    needle = (query_text or "").strip().lower()
    if needle and sort == "works" and direction is None:
        # Promote exact acronym / exact name hits to the top of search results.
        order_terms.append(
            case(
                (needle == any_(columns["acronyms"]), 0),
                (func.lower(columns["name"]) == needle, 0),
                else_=1,
            )
        )
    order_terms.extend([first, second, columns["name"].asc(), columns["ror"]])
    return stmt.order_by(*order_terms)


def _joint_works(
    institution: Institution,
    filters: CollaborationFilters,
    ror: str,
    deal_rors: frozenset[str] = frozenset(),
) -> Any:
    selected = _selected(institution, filters, deal_rors=deal_rors)
    return (
        select(
            selected.c.work.label("work"),
            selected.c.source,
            selected.c.corresponding,
            selected.c.home_corresponding,
        )
        .where(selected.c.ror == ror)
        .subquery()
    )


def _author_names() -> Any:
    name = func.btrim(func.concat_ws(" ", WorkPureAuthor.first_names, WorkPureAuthor.family_names))
    return (
        select(func.string_agg(name, aggregate_order_by(literal(", "), WorkPureAuthor.position)))
        .where(
            WorkPureAuthor.institution_id == Work.institution_id,
            WorkPureAuthor.work_pure_uuid == Work.pure_uuid,
        )
        .correlate(Work)
        .scalar_subquery()
    )


def _works_stmt(institution: Institution, joint: Any) -> Any:
    return (
        select(
            joint.c.work.label("pure_uuid"),
            joint.c.source,
            joint.c.corresponding,
            joint.c.home_corresponding,
            Work.title,
            Work.year,
            Work.doi_normalized,
            Work.oa_status,
            Work.journal_issn_l,
            Journal.title.label("journal_title"),
            func.coalesce(JournalFlags.deal_covered, False).label("deal_covered"),
            work_type_normalized(Work.work_type).label("work_type"),
            _author_names().label("authors"),
        )
        .select_from(joint)
        .join(Work, and_(Work.institution_id == institution.id, Work.pure_uuid == joint.c.work))
        .outerjoin(Journal, Journal.issn_l == Work.journal_issn_l)
        .outerjoin(
            JournalFlags,
            and_(
                JournalFlags.institution_id == institution.id,
                JournalFlags.issn_l == Work.journal_issn_l,
            ),
        )
        .order_by(Work.year.desc(), Work.title, joint.c.work)
    )


async def _work_author_links(
    session: AsyncSession, institution: Institution, work_uuids: Sequence[str]
) -> dict[str, list[CollaborationWorkAuthor]]:
    """Roster-linked UT authors per work, in author-position order."""
    if not work_uuids:
        return {}
    rows = (
        await session.execute(
            select(
                WorkPureAuthor.work_pure_uuid,
                WorkPureAuthor.person_uuid,
                func.btrim(
                    func.concat_ws(" ", WorkPureAuthor.first_names, WorkPureAuthor.family_names)
                ).label("name"),
                Author.pure_uuid.label("roster_uuid"),
            )
            .outerjoin(
                Author,
                and_(
                    Author.institution_id == WorkPureAuthor.institution_id,
                    Author.pure_uuid == WorkPureAuthor.person_uuid,
                ),
            )
            .where(
                WorkPureAuthor.institution_id == institution.id,
                WorkPureAuthor.work_pure_uuid.in_(list(work_uuids)),
            )
            .order_by(WorkPureAuthor.work_pure_uuid, WorkPureAuthor.position)
        )
    ).all()
    out: dict[str, list[CollaborationWorkAuthor]] = defaultdict(list)
    for r in rows:
        if not r.name:
            continue
        if len(out[r.work_pure_uuid]) < AUTHOR_CAP:
            out[r.work_pure_uuid].append(
                CollaborationWorkAuthor(pure_uuid=r.roster_uuid, name=r.name)
            )
    return out


# --- totals and facets -------------------------------------------------------


def _facet_counts(rows: Sequence[Any], limit: int = FACET_CAP) -> list[FacetCount]:
    return [
        FacetCount(value=str(v), count=int(n))
        for v, n in sorted(rows, key=lambda r: (-int(r[1]), str(r[0])))
    ][:limit]


async def _partner_attribute_counts(
    session: AsyncSession, selected: Any, column: Any
) -> list[FacetCount]:
    stmt = (
        select(column.label("value"), func.count(func.distinct(selected.c.work)))
        .select_from(selected)
        .join(PartnerInstitution, PartnerInstitution.ror == selected.c.ror)
        .where(column.is_not(None))
        .group_by(column)
    )
    return _facet_counts((await session.execute(stmt)).all())


async def _facet_org_type(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
    deal_rors: frozenset[str],
) -> list[FacetCount]:
    return await _partner_attribute_counts(
        session,
        _selected(institution, filters, partner="org_type", deal_rors=deal_rors),
        func.coalesce(func.lower(PartnerInstitution.org_type), "unknown"),
    )


async def _facet_country(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
    deal_rors: frozenset[str],
) -> list[FacetCount]:
    return await _partner_attribute_counts(
        session,
        _selected(institution, filters, partner="country", deal_rors=deal_rors),
        func.upper(PartnerInstitution.country_code),
    )


async def _facet_source(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
    deal_rors: frozenset[str],
) -> list[FacetCount]:
    selected = _selected(institution, filters, link="source", deal_rors=deal_rors)
    rows = await session.execute(
        select(selected.c.source, func.count(func.distinct(selected.c.work))).group_by(
            selected.c.source
        )
    )
    return _facet_counts(rows.all())


async def _facet_oa_status(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
    deal_rors: frozenset[str],
) -> list[FacetCount]:
    selected = _selected(institution, filters, work="oa_status", deal_rors=deal_rors)
    rows = await session.execute(
        select(func.lower(Work.oa_status), func.count(func.distinct(selected.c.work)))
        .select_from(selected)
        .join(
            Work,
            and_(Work.institution_id == institution.id, Work.pure_uuid == selected.c.work),
        )
        .where(Work.oa_status.is_not(None))
        .group_by(func.lower(Work.oa_status))
    )
    return _facet_counts(rows.all())


async def _facet_topic(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
    deal_rors: frozenset[str],
) -> list[FacetCount]:
    selected = _selected(institution, filters, work="topic", deal_rors=deal_rors)
    topic = _primary_topic()
    rows = await session.execute(
        select(topic, func.count(func.distinct(selected.c.work)))
        .select_from(selected)
        .join(
            Work,
            and_(Work.institution_id == institution.id, Work.pure_uuid == selected.c.work),
        )
        .join(Journal, Journal.issn_l == Work.journal_issn_l)
        .where(topic.is_not(None), topic != "")
        .group_by(topic)
    )
    return _facet_counts(rows.all())


async def _facet_orgunit(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
    deal_rors: frozenset[str],
) -> list[FacetCount]:
    selected = _selected(institution, filters, work="orgunit", deal_rors=deal_rors)
    key = unit_key(filters.level)
    stmt = (
        select(key.label("value"), func.count(func.distinct(Work.pure_uuid)))
        .where(
            *_work_conditions(institution, filters, drop="orgunit"),
            *unit_work_conditions(institution, filters.level),
            Work.pure_uuid.in_(select(selected.c.work)),
            key.is_not(None),
            func.btrim(key) != "",
        )
        .group_by(key)
    )
    return _facet_counts((await session.execute(stmt)).all())


async def _credit_facet(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
    deal_rors: frozenset[str],
    dimension: str,
    jisc_map: dict[str, int],
) -> list[Any]:
    selected = _selected(institution, filters, work=dimension, deal_rors=deal_rors)
    works = (
        select(Work.pure_uuid.label("work"))
        .where(
            *_work_conditions(institution, filters, drop=dimension),
            Work.pure_uuid.in_(select(selected.c.work)),
        )
        .subquery()
    )
    credits = _credits(institution, dimension)
    stmt = (
        select(
            credits.c.key.label("key"),
            _credit_name(credits).label("name"),
            func.max(credits.c.code).label("code"),
            func.max(credits.c.acronym).label("acronym"),
            func.count(func.distinct(credits.c.work)).label("count"),
            _credit_sources_list(credits).label("sources"),
        )
        .where(credits.c.work.in_(select(works.c.work)), credits.c.key.is_not(None))
        .group_by(credits.c.key)
    )
    rows = (await session.execute(stmt)).all()
    ordered = sorted(rows, key=lambda r: (-int(r.count), r.name or "", r.key))[:FACET_CAP]
    if dimension == "funder":
        return [
            CollaborationFunder(
                key=r.key,
                name=r.name or r.key,
                sources=sorted(r.sources),
                works=int(r.count),
                jisc_funder_id=_jisc_id(r.key, jisc_map),
            )
            for r in ordered
        ]
    return [
        CollaborationProject(
            key=r.key,
            code=r.code,
            acronym=r.acronym,
            funder=r.name,
            source="openaire" if "openaire" in r.sources else "openalex",
            sources=sorted(r.sources),
            works=int(r.count),
        )
        for r in ordered
    ]


def _jisc_id(funder_key: str, jisc_map: dict[str, int]) -> int | None:
    if not funder_key.startswith("openalex:"):
        return None
    return jisc_map.get(funder_key.removeprefix("openalex:"))


async def _overview_trend(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
    selected: Any,
    home_cc: str | None,
) -> tuple[list[CollaborationTrendYear], int, int, int, int]:
    """Per-year totals + domestic/international + OA + organisation-type split
    over the filtered collaborative works, plus overall domestic/international/
    OA/closed totals."""
    total_by_year = dict(
        (
            await session.execute(
                select(Work.year, func.count())
                .where(*_work_conditions(institution, filters))
                .group_by(Work.year)
            )
        ).all()
    )
    # Collapse selected links to one row per collaborative work so domestic/
    # international and OA counts never double-count multi-partner works.
    if home_cc:
        is_dom = func.bool_or(func.upper(PartnerInstitution.country_code) == home_cc)
        is_intl = func.bool_or(
            and_(
                PartnerInstitution.country_code.is_not(None),
                func.upper(PartnerInstitution.country_code) != home_cc,
            )
        )
    else:
        is_dom = literal(False)
        is_intl = literal(True)

    per_work = (
        select(
            selected.c.work.label("work"),
            is_dom.label("has_domestic"),
            is_intl.label("has_intl"),
        )
        .select_from(selected)
        .join(PartnerInstitution, PartnerInstitution.ror == selected.c.ror)
        .group_by(selected.c.work)
        .subquery()
    )
    rows = (
        await session.execute(
            select(
                Work.year,
                func.count().label("with_partner"),
                func.count().filter(per_work.c.has_domestic).label("domestic"),
                func.count().filter(per_work.c.has_intl).label("international"),
                *(
                    func.count().filter(func.lower(Work.oa_status) == st).label(f"oa_{st}")
                    for st in YEAR_BUCKETS
                ),
            )
            .select_from(per_work)
            .join(
                Work, and_(Work.institution_id == institution.id, Work.pure_uuid == per_work.c.work)
            )
            .group_by(Work.year)
            .order_by(Work.year)
        )
    ).all()
    by_year = {int(r.year): r for r in rows}
    org_type = func.coalesce(func.lower(PartnerInstitution.org_type), "unknown")
    type_counts: dict[int, dict[str, int]] = defaultdict(dict)
    for yr, kind, count in await session.execute(
        select(Work.year, org_type, func.count(func.distinct(selected.c.work)))
        .select_from(selected)
        .join(PartnerInstitution, PartnerInstitution.ror == selected.c.ror)
        .join(Work, and_(Work.institution_id == institution.id, Work.pure_uuid == selected.c.work))
        .group_by(Work.year, org_type)
    ):
        type_counts[int(yr)][kind] = int(count)
    all_years = sorted({int(y) for y in total_by_year if y is not None} | set(by_year))
    trend: list[CollaborationTrendYear] = []
    domestic_total = 0
    intl_total = 0
    oa_total = 0
    closed_total = 0
    for yr in all_years:
        r = by_year.get(yr)
        if r is not None:
            dom = int(r.domestic)
            intl = int(r.international)
            domestic_total += dom
            intl_total += intl
            oa_vals = {f"oa_{st}": int(getattr(r, f"oa_{st}")) for st in YEAR_BUCKETS}
            oa_total += sum(oa_vals[f"oa_{st}"] for st in OA_OPEN_STATUSES)
            closed_total += oa_vals["oa_closed"]
            trend.append(
                CollaborationTrendYear(
                    year=yr,
                    total_works=int(total_by_year.get(yr, 0)),
                    with_partner=int(r.with_partner),
                    domestic=dom,
                    international=intl,
                    **oa_vals,
                    by_org_type=type_counts.get(yr, {}),
                )
            )
        else:
            trend.append(
                CollaborationTrendYear(
                    year=yr,
                    total_works=int(total_by_year.get(yr, 0)),
                    with_partner=0,
                    domestic=0,
                    international=0,
                )
            )
    return trend, domestic_total, intl_total, oa_total, closed_total


async def _summary(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
    *,
    include_facets: bool,
    deal_rors: frozenset[str],
    jisc_map: dict[str, int],
) -> dict[str, Any]:
    """Totals, overview trend and (when requested) facets, cached per epoch."""
    key = (
        "collab_summary_v3",
        institution.id,
        filters.q,
        *(
            tuple(v) if v else ()
            for v in (
                filters.org_types,
                filters.countries,
                filters.faculty,
                filters.funders,
                filters.projects,
                filters.sources,
                filters.oa_statuses,
                filters.topics,
            )
        ),
        filters.level,
        filters.size,
        filters.rollup,
        filters.lead,
        filters.min_works,
        filters.shares_deals,
        filters.year_range,
        include_facets,
        await cache_epoch(session),
    )
    hit = cache_get(FACET_CACHE, key, SNAPSHOT_TTL)
    if hit is not None:
        return hit
    selected = _selected(institution, filters, deal_rors=deal_rors)
    total_works, with_partner, total_partners = (
        await session.execute(
            select(
                select(func.count())
                .select_from(Work)
                .where(*_work_conditions(institution, filters))
                .scalar_subquery(),
                select(func.count(func.distinct(selected.c.work))).scalar_subquery(),
                select(func.count(func.distinct(selected.c.ror))).scalar_subquery(),
            )
        )
    ).one()
    by_source: dict[_Payload, int] = {"openalex": 0, "openaire": 0}
    for source, count in await session.execute(
        select(selected.c.source, func.count(func.distinct(selected.c.work))).group_by(
            selected.c.source
        )
    ):
        by_source[_payload(source)] = int(count)
    year_from, year_to = (
        await session.execute(
            select(func.min(Work.year), func.max(Work.year)).where(
                *_work_conditions(institution, filters)
            )
        )
    ).one()
    home_cc = await _home_country(session, institution)
    trend, domestic_works, international_works, oa_works, closed_works = await _overview_trend(
        session, institution, filters, selected, home_cc
    )

    facets_dict: dict[str, Any] | None = None
    if include_facets:
        facet_jobs: list[tuple[str, Callable[[AsyncSession], Awaitable[Any]]]] = [
            ("org_type", lambda own: _facet_org_type(own, institution, filters, deal_rors)),
            ("country", lambda own: _facet_country(own, institution, filters, deal_rors)),
            ("orgunit", lambda own: _facet_orgunit(own, institution, filters, deal_rors)),
            ("oa_status", lambda own: _facet_oa_status(own, institution, filters, deal_rors)),
            ("topic", lambda own: _facet_topic(own, institution, filters, deal_rors)),
            (
                "funder",
                lambda own: _credit_facet(own, institution, filters, deal_rors, "funder", jisc_map),
            ),
            (
                "project",
                lambda own: _credit_facet(
                    own, institution, filters, deal_rors, "project", jisc_map
                ),
            ),
            ("source", lambda own: _facet_source(own, institution, filters, deal_rors)),
        ]

        def wrap(name: str, fn: Callable[[AsyncSession], Awaitable[Any]]):
            async def run(own: AsyncSession) -> tuple[str, Any]:
                return name, await fn(own)

            return run

        facets_dict = dict(await together(session, [wrap(n, fn) for n, fn in facet_jobs]))

    summary: dict[str, Any] = {
        "total_works": int(total_works),
        "works_with_partner": int(with_partner),
        "total_partners": int(total_partners),
        "domestic_works": domestic_works,
        "international_works": international_works,
        "oa_works": oa_works,
        "closed_works": closed_works,
        "works_by_source": by_source,
        "year_from": year_from,
        "year_to": year_to,
        "trend": trend,
        "facets": facets_dict,
    }
    cache_put(FACET_CACHE, key, summary)
    return summary


# --- rows to response models ----------------------------------------------


@dataclass(slots=True)
class _Credits:
    funders: list[CollaborationFunder]
    projects: list[CollaborationProject]


async def _credit_lists(
    session: AsyncSession,
    institution: Institution,
    selected: Any,
    rors: Sequence[str],
    cap: int,
    jisc_map: dict[str, int],
) -> dict[str, _Credits]:
    out: dict[str, _Credits] = {ror: _Credits([], []) for ror in rors}
    if not rors:
        return out
    rows: dict[tuple[str, str], list[Any]] = defaultdict(list)

    def dimension_rows(dimension: str) -> Callable[[AsyncSession], Awaitable[Sequence[Any]]]:
        credits = _credits(institution, dimension)
        stmt = (
            select(
                selected.c.ror.label("ror"),
                credits.c.key.label("key"),
                _credit_name(credits).label("name"),
                func.max(credits.c.code).label("code"),
                func.max(credits.c.acronym).label("acronym"),
                func.count(func.distinct(selected.c.work)).label("count"),
                _credit_sources_list(credits).label("sources"),
            )
            .select_from(selected)
            .join(credits, credits.c.work == selected.c.work)
            .where(selected.c.ror.in_(list(rors)), credits.c.key.is_not(None))
            .group_by(selected.c.ror, credits.c.key)
        )

        async def run(own: AsyncSession) -> Sequence[Any]:
            return (await own.execute(stmt)).all()

        return run

    for dimension, found in zip(
        ("funder", "project"),
        await together(session, [dimension_rows("funder"), dimension_rows("project")]),
        strict=True,
    ):
        for row in found:
            rows[(row.ror, dimension)].append(row)
    for (ror, dimension), entries in rows.items():
        entries.sort(key=lambda r: (-int(r.count), r.name or "", r.key))
        top = entries[:cap]
        if dimension == "funder":
            out[ror].funders = [
                CollaborationFunder(
                    key=e.key,
                    name=e.name or e.key,
                    sources=sorted(e.sources),
                    works=int(e.count),
                    jisc_funder_id=_jisc_id(e.key, jisc_map),
                )
                for e in top
            ]
        else:
            out[ror].projects = [
                CollaborationProject(
                    key=e.key,
                    code=e.code,
                    acronym=e.acronym,
                    funder=e.name,
                    source="openaire" if "openaire" in e.sources else "openalex",
                    sources=sorted(e.sources),
                    works=int(e.count),
                )
                for e in top
            ]
    return out


def _partner(
    row: Any,
    total_works: int,
    credits: _Credits,
    *,
    deal_rors: frozenset[str],
    merged_counts: dict[str, int],
    rollup: bool,
) -> CollaborationPartner:
    works = int(row.works)
    oa_works = int(row.oa_works or 0)
    return CollaborationPartner(
        ror=row.ror,
        name=row.name,
        org_type=row.org_type,
        country_code=row.country_code,
        city=row.city,
        lat=None if row.lat is None else float(row.lat),
        lng=None if row.lng is None else float(row.lng),
        parent_ror=row.parent_ror,
        parent_name=row.parent_name,
        in_ror=bool(row.in_ror),
        works=works,
        share=round(works / total_works, 4) if total_works else None,
        corresponding_works=int(row.corresponding_works),
        home_corresponding_works=int(row.home_corresponding_works or 0),
        authorships=int(row.authorships or 0),
        oa_works=oa_works,
        closed_works=int(row.closed_works or 0),
        oa_share=round(oa_works / works, 4) if works else None,
        shares_deals=row.ror in deal_rors,
        merged_count=merged_counts.get(row.ror, 0) if rollup else 0,
        sources=_sources(row.sources),
        funders=credits.funders,
        projects=credits.projects,
    )


def _work(row: Any, author_links: list[CollaborationWorkAuthor] | None = None) -> CollaborationWork:
    return CollaborationWork(
        pure_uuid=row.pure_uuid,
        title=row.title or "",
        year=int(row.year),
        doi=row.doi_normalized,
        work_type=row.work_type,
        corresponding=bool(row.corresponding),
        home_corresponding=bool(row.home_corresponding),
        oa_status=row.oa_status,
        journal_issn_l=row.journal_issn_l,
        journal_title=row.journal_title,
        deal_covered=bool(row.deal_covered),
        source=_payload(row.source),
        authors=[a for a in (row.authors or "").split(", ") if a][:AUTHOR_CAP],
        author_links=author_links or [],
    )


async def _ror_details(
    session: AsyncSession, institution: Institution, record: PartnerInstitution | None
) -> dict[str, Any]:
    payload: dict[str, Any] = record.payload if record and isinstance(record.payload, dict) else {}
    names = sorted(
        payload.get("names") or [],
        key=lambda name: "ror_display" not in (name.get("types") or []),
    )
    labels: list[str] = []
    for name in names:
        value = str(name.get("value") or "").strip()
        if value and value not in labels:
            labels.append(value)
    links = [
        CollaborationLink(type=str(link.get("type") or ""), value=str(link.get("value") or ""))
        for link in payload.get("links") or []
        if link.get("type") and link.get("value")
    ]
    raw_rels = [
        (str(rel.get("type") or ""), r, str(rel.get("label") or ""))
        for rel in payload.get("relationships") or []
        if (r := normalize_ror(rel.get("id"))) is not None
    ][:20]
    rel_rors = [r for _, r, _ in raw_rels]
    linked_rel_rors: set[str] = set()
    if rel_rors:
        linked_rel_rors = set(
            (
                await session.execute(
                    select(WorkPartner.partner_ror)
                    .distinct()
                    .where(
                        WorkPartner.institution_id == institution.id,
                        WorkPartner.partner_ror.in_(rel_rors),
                    )
                )
            ).scalars()
        )
    relationships = [
        CollaborationRelation(type=t, ror=r, label=lbl, is_partner=r in linked_rel_rors)
        for t, r, lbl in raw_rels
    ]
    return {
        "status": record.status if record else None,
        "openalex_id": record.openalex_id if record else None,
        "labels": labels[:12],
        "links": links[:20],
        "relationships": relationships,
    }


def _file_stem(institution: Institution, *parts: str) -> str:
    return safe_filename("-".join(p for p in (institution.code, *parts) if p))


async def _csv_lines(rows: Sequence[Sequence[Any]]) -> AsyncIterator[list[str]]:
    for row in rows:
        yield ["" if v is None else csv_safe(str(v)) for v in row]


async def _linked(session: AsyncSession, institution: Institution, ror: str) -> bool:
    """True when the institution has any direct or rolled-up link to `ror`."""
    direct = await session.scalar(
        select(WorkPartner.work_pure_uuid)
        .where(
            WorkPartner.institution_id == institution.id,
            WorkPartner.partner_ror == ror,
        )
        .limit(1)
    )
    if direct is not None:
        return True
    rolled = await session.scalar(
        select(WorkPartner.work_pure_uuid)
        .join(PartnerInstitution, PartnerInstitution.ror == WorkPartner.partner_ror)
        .where(
            WorkPartner.institution_id == institution.id,
            PartnerInstitution.rollup_ror == ror,
        )
        .limit(1)
    )
    return rolled is not None


# --- public API ---------------------------------------------------------------


async def search_collaborations(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
    *,
    sort: str,
    direction: str | None,
    offset: int,
    limit: int,
    include_facets: bool,
    include_credits: bool = False,
) -> CollaborationSearchResponse:
    deal_rors = await _shared_deal_rors(session, institution)
    merged_counts = await _merged_counts(session) if filters.rollup else {}
    jisc_map = await _jisc_funder_map(session) if (include_facets or include_credits) else {}
    selected = _selected(institution, filters, deal_rors=deal_rors)
    summary = await _summary(
        session,
        institution,
        filters,
        include_facets=include_facets,
        deal_rors=deal_rors,
        jisc_map=jisc_map,
    )
    rows = (
        await session.execute(
            _ordered(_per_partner(institution, selected), sort, direction, filters.q)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    if include_credits and rows:
        credits = await _credit_lists(
            session, institution, selected, [r.ror for r in rows], ITEM_LIST_CAP, jisc_map
        )
    else:
        credits = {r.ror: _Credits([], []) for r in rows}
    return CollaborationSearchResponse(
        items=[
            _partner(
                r,
                summary["total_works"],
                credits[r.ror],
                deal_rors=deal_rors,
                merged_counts=merged_counts,
                rollup=filters.rollup,
            )
            for r in rows
        ],
        total_partners=summary["total_partners"],
        total_works=summary["total_works"],
        works_with_partner=summary["works_with_partner"],
        domestic_works=summary["domestic_works"],
        international_works=summary["international_works"],
        oa_works=summary["oa_works"],
        closed_works=summary["closed_works"],
        works_by_source=summary["works_by_source"],
        year_from=summary["year_from"],
        year_to=summary["year_to"],
        trend=summary["trend"],
        facets=CollaborationFacets(**summary["facets"]) if summary["facets"] is not None else None,
    )


async def collaboration_map(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
) -> CollaborationMapResponse:
    deal_rors = await _shared_deal_rors(session, institution)
    merged_counts = await _merged_counts(session) if filters.rollup else {}
    per_partner = _per_partner(
        institution, _selected(institution, filters, deal_rors=deal_rors)
    ).subquery()
    rows = (
        await session.execute(
            select(
                per_partner.c.ror,
                per_partner.c.name,
                per_partner.c.country_code,
                per_partner.c.city,
                per_partner.c.org_type,
                per_partner.c.lat,
                per_partner.c.lng,
                per_partner.c.works,
                per_partner.c.corresponding_works,
                per_partner.c.home_corresponding_works,
                per_partner.c.oa_works,
            )
        )
    ).all()
    items = [
        CollaborationMapPoint(
            ror=r.ror,
            name=r.name,
            country_code=r.country_code,
            city=r.city,
            org_type=(r.org_type or "unknown").lower(),
            lat=float(r.lat),
            lng=float(r.lng),
            works=int(r.works),
            corresponding_works=int(r.corresponding_works),
            home_corresponding_works=int(r.home_corresponding_works or 0),
            oa_share=round(int(r.oa_works or 0) / int(r.works), 4) if int(r.works) else None,
            merged_count=merged_counts.get(r.ror, 0) if filters.rollup else 0,
        )
        for r in rows
        if r.lat is not None and r.lng is not None
    ]
    return CollaborationMapResponse(items=items, unmapped=len(rows) - len(items))


def _collab_filters_key(filters: CollaborationFilters) -> tuple[Any, ...]:
    return (
        filters.q,
        tuple(filters.org_types or ()),
        tuple(filters.countries or ()),
        filters.level,
        tuple(filters.faculty or ()),
        tuple(filters.funders or ()),
        tuple(filters.projects or ()),
        tuple(filters.sources or ()),
        tuple(filters.oa_statuses or ()),
        tuple(filters.topics or ()),
        filters.size,
        filters.rollup,
        filters.lead,
        filters.min_works,
        filters.shares_deals,
        filters.year_range,
    )


async def collaboration_detail(
    session: AsyncSession,
    institution: Institution,
    ror: str,
    filters: CollaborationFilters,
    *,
    include_works: bool = True,
) -> CollaborationDetailResponse | None:
    swr_key = ("collab_detail", institution.id, ror, _collab_filters_key(filters), include_works)
    epoch = await cache_epoch(session)
    fresh, bundle = swr_get(SWR_CACHE, swr_key, epoch)
    if fresh:
        return bundle
    if bundle is not None:
        swr_schedule(
            SWR_CACHE,
            swr_key,
            _collab_detail_factory(institution.id, ror, filters, include_works),
        )
        return bundle
    epoch, built = await _build_collaboration_detail(
        session, institution, ror, filters, include_works=include_works
    )
    if built is None:
        return None
    swr_put(SWR_CACHE, swr_key, epoch, built)
    return built


def _collab_detail_factory(iid: int, ror: str, filters: CollaborationFilters, include_works: bool):
    async def _factory():
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from ..db import get_engine

        async with async_sessionmaker(get_engine(), expire_on_commit=False)() as session:
            inst = (await session.scalars(select(Institution).where(Institution.id == iid))).one()
            return await _build_collaboration_detail(
                session, inst, ror, filters, include_works=include_works
            )

    return _factory


async def _build_collaboration_detail(
    session: AsyncSession,
    institution: Institution,
    ror: str,
    filters: CollaborationFilters,
    *,
    include_works: bool = True,
) -> tuple[Any, CollaborationDetailResponse | None]:
    if not await _linked(session, institution, ror):
        return await cache_epoch(session), None
    deal_rors = await _shared_deal_rors(session, institution)
    merged_counts = await _merged_counts(session) if filters.rollup else {}
    jisc_map = await _jisc_funder_map(session)
    selected = _selected(institution, filters, deal_rors=deal_rors)
    row = (
        await session.execute(_per_partner(institution, selected).where(selected.c.ror == ror))
    ).one_or_none()
    total_works = int(
        (
            await session.scalar(
                select(func.count())
                .select_from(Work)
                .where(*_work_conditions(institution, filters))
            )
        )
        or 0
    )
    if row is not None:
        credits = (
            await _credit_lists(session, institution, selected, [ror], DETAIL_LIST_CAP, jisc_map)
        )[ror]
        base = _partner(
            row,
            total_works,
            credits,
            deal_rors=deal_rors,
            merged_counts=merged_counts,
            rollup=filters.rollup,
        )
    else:
        record_stub = await session.get(PartnerInstitution, ror)
        base = CollaborationPartner(
            ror=ror,
            name=record_stub.name if record_stub and record_stub.name else ror,
            org_type=record_stub.org_type if record_stub else None,
            country_code=record_stub.country_code if record_stub else None,
            city=record_stub.city if record_stub else None,
            lat=float(record_stub.lat) if record_stub and record_stub.lat is not None else None,
            lng=float(record_stub.lng) if record_stub and record_stub.lng is not None else None,
            parent_ror=record_stub.parent_ror if record_stub else None,
            parent_name=record_stub.parent_name if record_stub else None,
            in_ror=record_stub is not None and record_stub.payload is not None,
            works=0,
            corresponding_works=0,
            home_corresponding_works=0,
            authorships=0,
            oa_works=0,
            closed_works=0,
            oa_share=None,
            shares_deals=ror in deal_rors,
            merged_count=merged_counts.get(ror, 0) if filters.rollup else 0,
            sources=[],
            funders=[],
            projects=[],
        )

    joint = _joint_works(institution, filters, ror, deal_rors=deal_rors)
    breakdowns = await detail_breakdowns(
        session,
        institution,
        ror,
        joint,
        rollup=filters.rollup,
        work_conds=_work_conditions(institution, filters),
        link_conds=_link_conditions(filters),
        together=together,
    )

    recent_items: list[CollaborationWork] = []
    if include_works:
        recent_rows = (
            await session.execute(_works_stmt(institution, joint).limit(RECENT_WORKS))
        ).all()
        author_links = await _work_author_links(
            session, institution, [r.pure_uuid for r in recent_rows]
        )
        recent_items = [_work(r, author_links.get(r.pure_uuid)) for r in recent_rows]

    record = await session.get(PartnerInstitution, ror)
    details = await _ror_details(session, institution, record)
    return await cache_epoch(session), CollaborationDetailResponse(
        **base.model_dump(),
        **details,
        **breakdowns,
        total_works=total_works,
        recent_works=recent_items,
    )


async def partner_works(
    session: AsyncSession,
    institution: Institution,
    ror: str,
    filters: CollaborationFilters,
    *,
    offset: int,
    limit: int,
) -> CollaborationWorksResponse | None:
    if not await _linked(session, institution, ror):
        return None
    deal_rors = await _shared_deal_rors(session, institution)
    joint = _joint_works(institution, filters, ror, deal_rors=deal_rors)
    total = await session.scalar(select(func.count()).select_from(joint))
    rows = (
        await session.execute(_works_stmt(institution, joint).offset(offset).limit(limit))
    ).all()
    author_links = await _work_author_links(session, institution, [r.pure_uuid for r in rows])
    return CollaborationWorksResponse(
        items=[_work(r, author_links.get(r.pure_uuid)) for r in rows],
        total=int(total or 0),
    )


async def collaborations_csv(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
) -> StreamingResponse:
    deal_rors = await _shared_deal_rors(session, institution)
    jisc_map = await _jisc_funder_map(session)
    selected = _selected(institution, filters, deal_rors=deal_rors)
    total_works = await session.scalar(
        select(func.count()).select_from(Work).where(*_work_conditions(institution, filters))
    )
    rows = (
        await session.execute(
            _ordered(_per_partner(institution, selected), "works", None, filters.q)
        )
    ).all()
    credits = await _credit_lists(
        session, institution, selected, [r.ror for r in rows], ITEM_LIST_CAP, jisc_map
    )
    table: list[list[Any]] = []
    for row in rows:
        works = int(row.works)
        oa_works = int(row.oa_works or 0)
        table.append(
            [
                row.ror,
                row.name,
                row.org_type,
                row.country_code,
                row.city,
                works,
                int(row.home_corresponding_works or 0),
                int(row.corresponding_works),
                int(row.authorships or 0),
                oa_works,
                int(row.closed_works or 0),
                round(oa_works / works, 4) if works else None,
                "yes" if row.ror in deal_rors else "no",
                round(works / total_works, 4) if total_works else None,
                " ".join(sorted(row.sources or [])),
                "; ".join(f.name for f in credits[row.ror].funders),
                "; ".join(
                    p.acronym or p.code or p.funder or p.key for p in credits[row.ror].projects
                ),
            ]
        )
    return csv_response(
        f"{_file_stem(institution, 'collaborations-partners')}.csv",
        _csv_lines(table),
        _PARTNER_CSV,
    )


async def collaborations_trend_csv(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
) -> StreamingResponse:
    """One row per publication year: all works, collaborative works and their
    domestic, open access and organisation-type split. Each `<type>_share` is
    the share of that year's collaborative works with a partner of that type."""
    summary = await _summary(
        session,
        institution,
        filters,
        include_facets=False,
        deal_rors=await _shared_deal_rors(session, institution),
        jisc_map={},
    )

    def share(part: int, whole: int) -> float | None:
        return round(part / whole, 4) if whole else None

    table: list[list[Any]] = []
    for y in summary["trend"]:
        row: list[Any] = [
            y.year,
            y.total_works,
            y.with_partner,
            share(y.with_partner, y.total_works),
            y.domestic,
            y.international,
            sum(getattr(y, f"oa_{st}") for st in OA_OPEN_STATUSES),
            y.oa_closed,
        ]
        for kind in _ORG_TYPES:
            count = y.by_org_type.get(kind, 0)
            row += [count, share(count, y.with_partner)]
        table.append(row)
    return csv_response(
        f"{_file_stem(institution, 'collaborations-trend')}.csv",
        _csv_lines(table),
        _TREND_CSV,
    )


async def partner_works_csv(
    session: AsyncSession,
    institution: Institution,
    ror: str,
    filters: CollaborationFilters,
) -> StreamingResponse | None:
    if not await _linked(session, institution, ror):
        return None
    deal_rors = await _shared_deal_rors(session, institution)
    joint = _joint_works(institution, filters, ror, deal_rors=deal_rors)
    rows = (await session.execute(_works_stmt(institution, joint))).all()
    table = [
        [
            r.pure_uuid,
            r.title,
            r.year,
            r.doi_normalized,
            r.work_type,
            r.journal_title,
            r.oa_status,
            "yes" if r.deal_covered else "no",
            "yes" if r.home_corresponding else "no",
            "yes" if r.corresponding else "no",
            r.source,
            r.authors,
        ]
        for r in rows
    ]
    return csv_response(
        f"{_file_stem(institution, 'collaborations', ror, 'works')}.csv",
        _csv_lines(table),
        _WORK_CSV,
    )
