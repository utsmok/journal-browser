"""Collaboration filters, SQL predicates, and query builders."""

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

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

from ...identifiers import bare_openalex_id, normalize_ror
from ...models import (
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
from ...queries import cache_epoch, work_type_normalized, work_type_not_excluded
from ...schemas import (
    CollaborationWorkAuthor,
)
from ..cache import (
    FACET_CACHE,
    SNAPSHOT_TTL,
    cache_get,
    cache_put,
)
from ..collaborations_detail import (
    OA_OPEN_STATUSES,
    STANDARD_MAX_PARTNERS,
    primary_topic_expr,
)
from ..works_query import (
    unit_work_conditions,
    work_window,
)

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
#: A programme label, one or more words followed by a programme year
#: (2000 to 2039): "HORIZON2020", "Horizon 2020", "France2030". The
#: narrower year keeps grant numbers such as DFG "GRK 2073".
_PROGRAMME_LABEL = r"^(?:[a-z]+[\s\-/]?)+20[0-3][0-9]$"

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
    a programme year (JST "JPMJCR2014"), against about 1,250 programme
    labels on 2026-11-24. A short
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
